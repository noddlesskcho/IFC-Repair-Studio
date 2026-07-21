from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from html import escape as html_escape
from io import StringIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.graphics.shapes import Drawing, Rect, String

from .models import RunReport
from .errors import CancelledError


APP_NAME = "IFC Repair Studio"
APP_VERSION = "0.4.2"
BLUE = colors.HexColor("#155eef")
NAVY = colors.HexColor("#172033")
MUTED = colors.HexColor("#64748b")
PALE = colors.HexColor("#eef4ff")
GREEN = colors.HexColor("#22863a")
AMBER = colors.HexColor("#b45309")


def _format_bytes(value: int) -> str:
    amount = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value:,} B"


def _duration(report: RunReport) -> float:
    return report.total_duration_seconds or sum(report.durations.values())


def _counts(report: RunReport) -> dict[str, int]:
    repaired = report.summary_counts.get(
        "SuccessfullyRepaired", sum(1 for item in report.diagnoses if item.repaired)
    )
    remaining = report.summary_counts.get(
        "TargetedIssuesRemaining", sum(1 for item in report.diagnoses if not item.repaired)
    )
    return {
        "elements_scanned": report.summary_counts.get("ElementsScanned", 0),
        "elements_affected": report.summary_counts.get("ElementsAffected", 0),
        "representations_scanned": report.summary_counts.get("RepresentationsScanned", 0),
        "affected": report.summary_counts.get("AffectedRepresentations", len(report.diagnoses)),
        "repairable": report.summary_counts.get("AutomaticallyRepairable", 0),
        "not_repairable": report.summary_counts.get("NotAutomaticallyRepairable", 0),
        "repaired": repaired,
        "remaining": remaining,
    }


def _repair_types(report: RunReport) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in report.diagnoses:
        label = f"{item.representation_identifier or 'Unidentified'} / {item.representation_type or 'Unspecified'}"
        result[label] = result.get(label, 0) + 1
    return result


def _records(
    report: RunReport, cancelled: Callable[[], bool] | None = None,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index, item in enumerate(report.diagnoses, 1):
        if cancelled and index % 100 == 0 and cancelled():
            raise CancelledError("Report generation cancelled safely")
        proposed = item.proposed_context.step_id if item.proposed_context else None
        evidence = "; ".join(item.evidence + item.conflicts) or "No supporting evidence recorded"
        records.append({
            "step_id": item.product_step_id,
            "global_id": item.product_global_id or "",
            "element": item.product_class or "",
            "name": item.product_name or "",
            "representation_step_id": item.representation_step_id,
            "representation": (
                f"{item.representation_identifier or '-'} / {item.representation_type or '-'}"
            ),
            "old_context": item.current_context_step_id,
            "new_context": proposed,
            "rule": item.rule_id or report.active_rule_id,
            "confidence": round(item.confidence * 100, 1),
            "verification": item.validation_result,
            "status": item.status.value,
            "repaired": item.repaired,
            "evidence": evidence,
            "item_count": item.item_count,
            "item_classes": ", ".join(item.item_classes),
            "decision_trace": item.decision_trace,
        })
    return records


class IReportBuilder(ABC):
    @abstractmethod
    def build(self, report: RunReport, path: Path) -> Path:
        """Build one user-facing report and return its path."""


class PDFReportBuilder(IReportBuilder):
    """Concise executive report. Detailed repair records intentionally stay in HTML."""

    def build(self, report: RunReport, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name="CoverTitle", parent=styles["Title"], fontName="Helvetica-Bold",
            fontSize=28, leading=33, alignment=TA_LEFT, textColor=BLUE,
        ))
        styles.add(ParagraphStyle(
            name="CoverSub", parent=styles["Heading1"], fontName="Helvetica-Bold",
            fontSize=20, leading=25, textColor=NAVY,
        ))
        styles.add(ParagraphStyle(
            name="Section", parent=styles["Heading1"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, textColor=NAVY, spaceAfter=5 * mm,
        ))
        styles.add(ParagraphStyle(
            name="BodySmall", parent=styles["BodyText"], fontName="Helvetica",
            fontSize=8.5, leading=11.5, textColor=NAVY,
        ))
        styles.add(ParagraphStyle(
            name="Muted", parent=styles["BodyText"], fontName="Helvetica",
            fontSize=8.5, leading=11.5, textColor=MUTED,
        ))
        styles.add(ParagraphStyle(
            name="KPI", parent=styles["BodyText"], fontName="Helvetica-Bold",
            fontSize=18, leading=21, textColor=NAVY, alignment=TA_CENTER,
        ))
        styles.add(ParagraphStyle(
            name="KPILabel", parent=styles["BodyText"], fontName="Helvetica",
            fontSize=7.5, leading=10, textColor=MUTED, alignment=TA_CENTER,
        ))
        counts = _counts(report)
        verification_passed = bool(report.targeted_verification.get("passed"))
        timestamp = report.finished_at or datetime.now().astimezone().isoformat()

        def p(value: object, style: str = "BodySmall") -> Paragraph:
            shown = "-" if value in (None, "") else str(value)
            return Paragraph(escape(shown), styles[style])

        def section(title: str) -> list[object]:
            return [Paragraph(title, styles["Section"]), Spacer(1, 1 * mm)]

        def key_value(rows: list[tuple[object, object]]) -> Table:
            table = Table([[p(k), p(v)] for k, v in rows], colWidths=[48 * mm, 132 * mm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), PALE),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            return table

        def statistics_chart() -> Drawing:
            values = [
                ("Affected", counts["affected"], BLUE),
                ("Auto repairable", counts["repairable"], colors.HexColor("#2563eb")),
                ("Repaired", counts["repaired"], GREEN),
                ("Remaining", counts["remaining"], AMBER),
            ]
            maximum = max(1, *(value for _, value, _ in values))
            drawing = Drawing(180 * mm, 40 * mm)
            for index, (label, value, colour) in enumerate(values):
                y = 31 * mm - index * 9 * mm
                drawing.add(String(0, y + 1.2 * mm, label, fontName="Helvetica", fontSize=8, fillColor=NAVY))
                drawing.add(Rect(37 * mm, y, 115 * mm, 4 * mm, fillColor=colors.HexColor("#e8edf4"), strokeColor=None))
                drawing.add(Rect(37 * mm, y, 115 * mm * value / maximum, 4 * mm, fillColor=colour, strokeColor=None))
                drawing.add(String(157 * mm, y + 1.1 * mm, f"{value:,}", fontName="Helvetica-Bold", fontSize=8, fillColor=NAVY))
            return drawing

        story: list[object] = [
            Spacer(1, 34 * mm), Paragraph(APP_NAME, styles["CoverTitle"]),
            Spacer(1, 5 * mm), Paragraph("Repair Report", styles["CoverSub"]),
            Spacer(1, 18 * mm), p(Path(report.source).name),
            Spacer(1, 55 * mm),
            key_value([
                ("Generated", timestamp), ("Application version", APP_VERSION),
                ("Repair rule version", f"{report.active_rule_id} v{report.active_rule_version}"),
                ("Verification", "PASS" if verification_passed else "NOT COMPLETED"),
            ]),
            PageBreak(),
        ]

        story += section("Executive Summary")
        kpis = [
            (counts["elements_scanned"], "Elements Scanned"),
            (counts["elements_affected"], "Affected Elements"),
            (counts["repaired"], "Representations Repaired"),
            (counts["remaining"], "Remaining Issues"),
            ("PASS" if verification_passed else "CHECK", "Verification"),
        ]
        cards = Table(
            [[p(value, "KPI") for value, _ in kpis], [p(label, "KPILabel") for _, label in kpis]],
            colWidths=[36 * mm] * 5,
        )
        cards.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
        ]))
        story += [cards, Spacer(1, 10 * mm), Paragraph("File Information", styles["Heading2"]),
                  key_value([
                      ("Input IFC", report.source), ("Output IFC", report.output or "Not written"),
                      ("Schema", report.schema or "Unknown"),
                      ("Input size", _format_bytes(report.input_size)),
                      ("Output size", _format_bytes(report.output_size)),
                      ("Duration", f"{_duration(report):.2f} seconds"),
                      ("Repair rule", report.active_rule_id),
                  ]), PageBreak()]

        story += section("Repair Scope")
        story += [key_value([
            ("Rule", report.active_rule_id), ("Rule version", report.active_rule_version),
            ("Element scope", "IfcSlab"),
            ("Representations", "Body / SweptSolid; FootPrint / Curve2D"),
            ("Ownership", "Direct ownership only"),
            ("Excluded", "Other IFC elements, representation maps and shape aspects"),
        ]), Spacer(1, 10 * mm), Paragraph("Performance Summary", styles["Heading2"])]
        performance = [
            ("Open IFC", report.durations.get("ifc_opening", 0.0)),
            ("Target slabs", report.durations.get("collect_target_slabs", 0.0)),
            ("Shape representations", report.durations.get("collect_shape_representations", 0.0)),
            ("Context resolution", report.durations.get("context_resolution", 0.0)),
            ("Patch plan", report.durations.get("build_patch_plan", 0.0)),
            ("Apply patches", report.durations.get("apply_patches", 0.0)),
            ("Flush", report.durations.get("flush_output", 0.0)),
            ("STEP envelope", report.durations.get("step_envelope_verification", 0.0)),
            ("Verification", report.durations.get("targeted_verification", 0.0)),
            ("Change audit", report.durations.get("unexpected_change_audit", 0.0)),
            ("Total", _duration(report)),
        ]
        story += [key_value([(name, f"{seconds:.3f} seconds") for name, seconds in performance]), PageBreak()]

        story += section("Repair Statistics")
        type_rows = [(name, f"{count:,}") for name, count in _repair_types(report).items()]
        if not type_rows:
            type_rows = [("No targeted issues", "0")]
        story += [statistics_chart(), Spacer(1, 5 * mm), key_value([
            ("Affected representations", f"{counts['affected']:,}"),
            ("Automatically repairable", f"{counts['repairable']:,}"),
            ("Not automatically repairable", f"{counts['not_repairable']:,}"),
            ("Successfully repaired", f"{counts['repaired']:,}"),
            ("Remaining", f"{counts['remaining']:,}"),
        ] + type_rows), Spacer(1, 10 * mm), Paragraph("Verification", styles["Heading2"]),
        key_value([
            ("Targeted verification", "PASS" if verification_passed else "NOT COMPLETED"),
            ("Intended", report.targeted_verification.get("intended", 0)),
            ("Verified", report.targeted_verification.get("verified", 0)),
            ("Remaining", report.targeted_verification.get("remaining", counts["remaining"])),
            ("Full IFC validation", "Performed" if report.full_validation_performed else "Not requested"),
            ("Unexpected modified records", report.change_audit.get("unexpected_modified_records", "Not run")),
        ]), PageBreak()]

        warnings = list(report.errors)
        warnings.extend(issue.message for issue in report.validation_after)
        warnings.extend(
            item for diagnosis in report.diagnoses if not diagnosis.repaired
            for item in (diagnosis.conflicts or ["Repair was skipped"])
        )
        omitted_warning_count = max(0, len(warnings) - 100)
        warnings = warnings[:100]
        if omitted_warning_count:
            warnings.append(
                f"{omitted_warning_count:,} additional warnings are available in the HTML report."
            )
        story += section("Warnings and Submission Notes")
        if warnings:
            story += [p(f"{index}. {warning}") for index, warning in enumerate(warnings, 1)]
        else:
            story += [p("No skipped repairs, validation warnings or runtime warnings were recorded.")]
        story += [Spacer(1, 10 * mm), KeepTogether([
            Paragraph("Detailed Engineering Record", styles["Heading2"]),
            p("Detailed repair records are available in the HTML Report. The HTML report works offline and supports search, filters, sorting and on-demand CSV or JSON export."),
        ])]

        def footer(canvas: object, document: object) -> None:
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor("#dce3ec"))
            canvas.line(15 * mm, 13 * mm, 195 * mm, 13 * mm)
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(MUTED)
            footer_text = (
                f"Generated by {APP_NAME} | v{APP_VERSION} | "
                f"Rule v{report.active_rule_version} | {timestamp}"
            )
            canvas.drawString(15 * mm, 8.5 * mm, footer_text[:125])
            canvas.drawRightString(195 * mm, 8.5 * mm, f"Page {document.page}")
            canvas.restoreState()

        document = SimpleDocTemplate(
            str(path), pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm,
            topMargin=16 * mm, bottomMargin=19 * mm,
            title=f"{APP_NAME} - Repair Report", author=APP_NAME,
        )
        document.build(story, onFirstPage=footer, onLaterPages=footer)
        return path


class HTMLReportBuilder(IReportBuilder):
    """Complete, dependency-free engineering report with client-side exploration."""

    def __init__(self, cancelled: Callable[[], bool] | None = None) -> None:
        self.cancelled = cancelled

    def build(self, report: RunReport, path: Path) -> Path:
        if self.cancelled and self.cancelled():
            raise CancelledError("HTML report generation cancelled safely")
        path.parent.mkdir(parents=True, exist_ok=True)
        counts = _counts(report)
        records_json = json.dumps(
            _records(report, self.cancelled), ensure_ascii=False
        ).replace("</", "<\\/")
        stage_rows = "".join(
            f"<tr><td>{html_escape(key.replace('_', ' ').title())}</td><td>{value:.3f} s</td></tr>"
            for key, value in report.durations.items()
        ) or "<tr><td colspan='2'>No stage timings recorded</td></tr>"
        type_rows = "".join(
            f"<div class='bar-row'><span>{html_escape(name)}</span><div class='bar'><i style='width:{(count / max(1, counts['affected'])) * 100:.1f}%'></i></div><b>{count:,}</b></div>"
            for name, count in _repair_types(report).items()
        ) or "<p class='muted'>No targeted repair types detected.</p>"
        warnings = list(report.errors) + [issue.message for issue in report.validation_after]
        warnings_html = "".join(f"<li>{html_escape(item)}</li>" for item in warnings) or "<li>None recorded</li>"
        verification = "PASS" if report.targeted_verification.get("passed") else "NOT COMPLETED"
        html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{APP_NAME} - Engineering Repair Report</title>
<style>
:root{{--bg:#f3f6fa;--card:#fff;--text:#172033;--muted:#64748b;--line:#dce3ec;--blue:#155eef;--green:#22863a;--soft:#eef4ff;--shadow:0 4px 18px #17203312}}
[data-theme=dark]{{--bg:#0f1722;--card:#172334;--text:#edf2f7;--muted:#a3afc0;--line:#34445a;--blue:#79a8ff;--green:#70d384;--soft:#203552;--shadow:none}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Segoe UI",Arial,sans-serif}}button,input,select{{font:inherit}}pre{{white-space:pre-wrap;word-break:break-word;font-size:12px}}
header{{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:14px 4vw;display:flex;align-items:center;gap:18px}}header h1{{font-size:18px;margin:0}}header .grow{{flex:1}}button{{border:1px solid var(--line);border-radius:7px;background:var(--card);color:var(--text);padding:8px 12px;cursor:pointer}}button:hover{{border-color:var(--blue)}}
nav{{display:flex;gap:4px;overflow:auto;padding:9px 4vw;background:var(--card);border-bottom:1px solid var(--line)}}nav a{{white-space:nowrap;color:var(--muted);text-decoration:none;padding:7px 11px;border-radius:6px}}nav a:hover{{background:var(--soft);color:var(--blue)}}
main{{max-width:1440px;margin:auto;padding:24px 4vw 60px}}section{{scroll-margin-top:105px;margin-bottom:24px}}h2{{font-size:19px;margin:0 0 12px}}h3{{font-size:14px;margin:18px 0 8px}}.grid{{display:grid;grid-template-columns:repeat(5,minmax(145px,1fr));gap:12px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;box-shadow:var(--shadow)}}.kpi strong{{display:block;font-size:25px}}.kpi span,.muted{{color:var(--muted)}}.pass{{color:var(--green)}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}dl{{display:grid;grid-template-columns:160px 1fr;gap:8px;margin:0}}dt{{color:var(--muted)}}dd{{margin:0;overflow-wrap:anywhere}}.bar-row{{display:grid;grid-template-columns:190px 1fr 60px;gap:10px;align-items:center;margin:9px 0}}.bar{{height:9px;background:var(--soft);border-radius:9px;overflow:hidden}}.bar i{{display:block;height:100%;background:var(--blue)}}.donut{{width:96px;height:96px;border-radius:50%;margin:10px auto;background:conic-gradient(var(--green) 0 var(--repaired),#f59e0b var(--repaired) 100%);display:grid;place-items:center}}.donut:after{{content:attr(data-label);width:66px;height:66px;border-radius:50%;background:var(--card);display:grid;place-items:center;font-weight:700}}
.tools{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}}input,select{{border:1px solid var(--line);border-radius:7px;background:var(--card);color:var(--text);padding:8px 10px}}input{{min-width:260px;flex:1}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:9px}}table{{border-collapse:collapse;width:100%;background:var(--card)}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:9px 10px;vertical-align:top;white-space:nowrap}}th{{background:var(--soft);cursor:pointer;position:sticky;top:0}}td.wrap{{white-space:normal;min-width:260px}}tr:hover td{{background:var(--soft)}}.pager{{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:10px}}code{{font-family:Consolas,monospace}}details{{border-top:1px solid var(--line);padding:10px 0}}.copy{{padding:2px 6px;font-size:12px}}footer{{color:var(--muted);text-align:center;padding:25px}}
@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr)}}.two{{grid-template-columns:1fr}}dl{{grid-template-columns:120px 1fr}}}}
</style></head>
<body><header><h1>{APP_NAME}</h1><span class="muted">Engineering Repair Report</span><span class="grow"></span><button id="theme">Dark mode</button></header>
<nav><a href="#overview">Overview</a><a href="#statistics">Repair Statistics</a><a href="#records">Repair Records</a><a href="#performance">Performance</a><a href="#diagnostics">Diagnostics</a><a href="#settings">Settings</a></nav>
<main>
<section id="overview"><h2>Overview</h2><div class="grid">
<div class="card kpi"><strong>{counts['elements_scanned']:,}</strong><span>Elements scanned</span></div>
<div class="card kpi"><strong>{counts['elements_affected']:,}</strong><span>Affected elements</span></div>
<div class="card kpi"><strong>{counts['repaired']:,}</strong><span>Representations repaired</span></div>
<div class="card kpi"><strong>{counts['remaining']:,}</strong><span>Remaining issues</span></div>
<div class="card kpi"><strong class="{'pass' if verification == 'PASS' else ''}">{verification}</strong><span>Targeted verification</span></div></div>
<div class="two" style="margin-top:14px"><div class="card"><h3>File information</h3><dl>
<dt>Input IFC</dt><dd>{html_escape(report.source)}</dd><dt>Output IFC</dt><dd>{html_escape(report.output or 'Not written')}</dd>
<dt>Schema</dt><dd>{html_escape(report.schema or 'Unknown')}</dd><dt>Input size</dt><dd>{_format_bytes(report.input_size)}</dd><dt>Output size</dt><dd>{_format_bytes(report.output_size)}</dd><dt>Total duration</dt><dd>{_duration(report):.3f} seconds</dd></dl></div>
<div class="card"><h3>Repair scope</h3><dl><dt>Rule</dt><dd>{html_escape(report.active_rule_id)}</dd><dt>Version</dt><dd>{html_escape(report.active_rule_version)}</dd><dt>Element</dt><dd>IfcSlab</dd><dt>Representations</dt><dd>Body / SweptSolid; FootPrint / Curve2D</dd><dt>Ownership</dt><dd>Direct ownership only</dd></dl></div></div></section>
<section id="statistics"><h2>Repair Statistics</h2><div class="two"><div class="card"><h3>Repair outcome</h3><div class="donut" style="--repaired:{counts['repaired']/max(1,counts['affected'])*100:.1f}%" data-label="{counts['repaired']:,} fixed"></div>
<div class="bar-row"><span>Automatically repairable</span><div class="bar"><i style="width:{counts['repairable']/max(1,counts['affected'])*100:.1f}%"></i></div><b>{counts['repairable']:,}</b></div>
<div class="bar-row"><span>Repaired</span><div class="bar"><i style="width:{counts['repaired']/max(1,counts['affected'])*100:.1f}%"></i></div><b>{counts['repaired']:,}</b></div>
<div class="bar-row"><span>Remaining</span><div class="bar"><i style="width:{counts['remaining']/max(1,counts['affected'])*100:.1f}%"></i></div><b>{counts['remaining']:,}</b></div></div>
<div class="card"><h3>Representation types</h3>{type_rows}</div></div></section>
<section id="records"><h2>Repair Records</h2><div class="card"><div class="tools"><input id="search" placeholder="Search STEP ID, GlobalId, name, representation or evidence"><select id="typeFilter"><option value="">All representations</option></select><select id="verifyFilter"><option value="">All verification results</option></select><button id="next">Jump to next</button><button id="csv">Export filtered CSV</button><button id="json">Export filtered JSON</button></div>
<div class="table-wrap"><table><thead><tr><th data-sort="step_id">STEP ID</th><th data-sort="global_id">GlobalId</th><th data-sort="element">Element</th><th data-sort="name">Name</th><th data-sort="representation">Representation</th><th data-sort="old_context">Old Context</th><th data-sort="new_context">New Context</th><th data-sort="rule">Rule</th><th data-sort="confidence">Confidence</th><th data-sort="verification">Verification</th><th>Details</th></tr></thead><tbody id="rows"></tbody></table></div><div class="pager"><button id="prev">Previous</button><span id="page"></span><button id="pageNext">Next</button></div></div></section>
<section id="performance"><h2>Performance</h2><div class="two"><div class="card"><h3>Execution timeline</h3><table><tbody>{stage_rows}</tbody></table></div><div class="card"><h3>Duration comparison</h3>{''.join(f'''<div class="bar-row"><span>{html_escape(k.replace('_',' ').title())}</span><div class="bar"><i style="width:{v/max(.001,_duration(report))*100:.1f}%"></i></div><b>{v:.2f}s</b></div>''' for k,v in report.durations.items())}</div></div></section>
<section id="diagnostics"><h2>Diagnostics</h2><div class="two"><div class="card"><h3>Warnings and exceptions</h3><ul>{warnings_html}</ul><h3>Verification messages</h3><ul>{''.join(f'<li>{html_escape(str(m))}</li>' for m in report.targeted_verification.get('messages', [])) or '<li>None recorded</li>'}</ul></div><div class="card"><h3>Execution details</h3><dl><dt>Temporary output</dt><dd>{html_escape(report.temporary_path or 'Cleaned up')}</dd><dt>Output size</dt><dd>{_format_bytes(report.output_size)}</dd><dt>Skipped repairs</dt><dd>{counts['not_repairable']:,}</dd><dt>Full validation</dt><dd>{'Performed' if report.full_validation_performed else 'Not requested'}</dd><dt>Expected changed records</dt><dd>{report.change_audit.get('expected_modified_records','Not run')}</dd><dt>Actual changed records</dt><dd>{report.change_audit.get('actual_modified_records','Not run')}</dd><dt>Unexpected changes</dt><dd>{report.change_audit.get('unexpected_modified_records','Not run')}</dd><dt>Write throughput</dt><dd>{_format_bytes(int(report.system_diagnostics.get('write_throughput_bytes_per_second') or 0))}/s</dd><dt>Peak working set</dt><dd>{_format_bytes(int(report.system_diagnostics.get('process_peak_working_set_bytes') or 0))}</dd><dt>Disk free</dt><dd>{_format_bytes(int(report.system_diagnostics.get('disk_free_bytes') or report.system_diagnostics.get('available_free_bytes') or 0))}</dd></dl></div></div></section>
<section id="settings"><h2>Settings</h2><div class="card"><dl><dt>Application</dt><dd>{APP_NAME} v{APP_VERSION}</dd><dt>Rule</dt><dd>{html_escape(report.active_rule_id)} v{html_escape(report.active_rule_version)}</dd><dt>Repair mode</dt><dd>{html_escape(report.repair_mode or 'Scan only')}</dd><dt>Python</dt><dd>{html_escape(report.environment.get('python_version','Unknown'))}</dd><dt>IfcOpenShell</dt><dd>{html_escape(report.environment.get('ifcopenshell_version','Unknown'))}</dd></dl></div></section>
</main><footer>Generated by {APP_NAME} v{APP_VERSION} | {html_escape(report.finished_at or '')}</footer>
<script>const records={records_json};let filtered=[...records],page=1,sortKey='step_id',ascending=true;const pageSize=50;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const copy=v=>navigator.clipboard?navigator.clipboard.writeText(String(v??'')):void 0;
function options(id,key){{const el=document.getElementById(id);[...new Set(records.map(r=>r[key]).filter(Boolean))].sort().forEach(v=>el.insertAdjacentHTML('beforeend',`<option>${{esc(v)}}</option>`))}}options('typeFilter','representation');options('verifyFilter','verification');
function apply(){{const q=document.getElementById('search').value.toLowerCase(),t=document.getElementById('typeFilter').value,v=document.getElementById('verifyFilter').value;filtered=records.filter(r=>(!q||Object.values(r).join(' ').toLowerCase().includes(q))&&(!t||r.representation===t)&&(!v||r.verification===v));filtered.sort((a,b)=>{{let x=a[sortKey]??'',y=b[sortKey]??'';return(x>y?1:x<y?-1:0)*(ascending?1:-1)}});page=1;render()}}
function render(){{const pages=Math.max(1,Math.ceil(filtered.length/pageSize));page=Math.min(page,pages);const rows=filtered.slice((page-1)*pageSize,page*pageSize);document.getElementById('rows').innerHTML=rows.map((r,i)=>`<tr id="record-${{i}}"><td><code>#${{esc(r.step_id)}}</code> <button class="copy" data-copy="${{esc(r.step_id)}}">Copy</button></td><td><code>${{esc(r.global_id)}}</code> <button class="copy" data-copy="${{esc(r.global_id)}}">Copy</button></td><td>${{esc(r.element)}}</td><td>${{esc(r.name)}}</td><td>${{esc(r.representation)}} (#${{esc(r.representation_step_id)}})</td><td>${{esc(r.old_context)}}</td><td>${{esc(r.new_context)}}</td><td>${{esc(r.rule)}}</td><td>${{esc(r.confidence)}}%</td><td>${{esc(r.verification)}}</td><td class="wrap"><details><summary>Expand</summary><b>Status:</b> ${{esc(r.status)}}<br><b>Items:</b> ${{esc(r.item_count)}} (${{esc(r.item_classes)}})<br><b>Evidence:</b> ${{esc(r.evidence)}}<br><b>Decision trace:</b><pre>${{esc(JSON.stringify(r.decision_trace,null,2))}}</pre></details></td></tr>`).join('')||'<tr><td colspan="11">No matching repair records.</td></tr>';document.getElementById('page').textContent=`Page ${{page}} of ${{pages}} | ${{filtered.length}} records`;document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>copy(b.dataset.copy))}}
['search','typeFilter','verifyFilter'].forEach(id=>document.getElementById(id).addEventListener(id==='search'?'input':'change',apply));document.querySelectorAll('[data-sort]').forEach(h=>h.onclick=()=>{{ascending=sortKey===h.dataset.sort?!ascending:true;sortKey=h.dataset.sort;apply()}});document.getElementById('prev').onclick=()=>{{page=Math.max(1,page-1);render()}};document.getElementById('pageNext').onclick=()=>{{page++;render()}};document.getElementById('next').onclick=()=>{{const row=document.querySelector('#rows tr');if(row)row.scrollIntoView({{behavior:'smooth',block:'center'}})}};
function download(name,type,text){{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{{type}}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}}
document.getElementById('json').onclick=()=>download('{html_escape(Path(report.source).stem)}_repair_records.json','application/json',JSON.stringify(filtered,null,2));document.getElementById('csv').onclick=()=>{{const keys=Object.keys(records[0]||{{}}),quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';download('{html_escape(Path(report.source).stem)}_repair_records.csv','text/csv;charset=utf-8','\\ufeff'+[keys.join(','),...filtered.map(r=>keys.map(k=>quote(r[k])).join(','))].join('\\r\\n'))}};
document.getElementById('theme').onclick=()=>{{const dark=document.documentElement.dataset.theme!=='dark';document.documentElement.dataset.theme=dark?'dark':'light';document.getElementById('theme').textContent=dark?'Light mode':'Dark mode';localStorage.setItem('ifc-report-theme',dark?'dark':'light')}};if(localStorage.getItem('ifc-report-theme')==='dark')document.getElementById('theme').click();render();</script></body></html>"""
        path.write_text(html, encoding="utf-8")
        return path


class ExportService:
    """Explicit machine-readable exports for integrations and user-requested extracts."""

    @staticmethod
    def write_json(report: RunReport | dict[str, object], path: Path) -> Path:
        data = report.to_dict() if isinstance(report, RunReport) else report
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def write_csv(report: RunReport, path: Path) -> Path:
        rows = _records(report)
        fields = list(rows[0]) if rows else [
            "step_id", "global_id", "element", "name", "representation",
            "old_context", "new_context", "rule", "confidence", "verification", "evidence",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    @staticmethod
    def csv_text(report: RunReport) -> str:
        stream = StringIO()
        rows = _records(report)
        fields = list(rows[0]) if rows else []
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue()


def write_json(report: RunReport | dict[str, object], path: Path) -> None:
    """Compatibility entry point. JSON is generated only when explicitly called."""
    ExportService.write_json(report, path)


def write_csv(report: RunReport, path: Path) -> None:
    """Compatibility entry point. CSV is generated only when explicitly called."""
    ExportService.write_csv(report, path)


def write_pdf(report: RunReport, path: Path) -> None:
    PDFReportBuilder().build(report, path)


def write_html(
    report: RunReport, path: Path,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    HTMLReportBuilder(cancelled).build(report, path)


class ReportGenerator:
    def __init__(self, builders: dict[str, IReportBuilder] | None = None) -> None:
        self.builders = builders or {
            "pdf": PDFReportBuilder(),
            "html": HTMLReportBuilder(),
        }

    def generate(self, report: RunReport, base: Path) -> dict[str, Path]:
        base.parent.mkdir(parents=True, exist_ok=True)
        stem = base.with_suffix("")
        return {
            extension: builder.build(report, stem.with_suffix(f".{extension}"))
            for extension, builder in self.builders.items()
        }


def write_bundle(report: RunReport, base: Path) -> dict[str, Path]:
    """Generate the two professional user-facing reports only: PDF and HTML."""
    return ReportGenerator().generate(report, base)
