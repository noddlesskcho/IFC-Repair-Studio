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
from .utils import format_bytes


APP_NAME = "IFC+SG Repair Assistant"
APP_VERSION = "1.0.0"
BLUE = colors.HexColor("#155eef")
NAVY = colors.HexColor("#172033")
MUTED = colors.HexColor("#64748b")
PALE = colors.HexColor("#eef4ff")
GREEN = colors.HexColor("#22863a")
AMBER = colors.HexColor("#b45309")


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
        "supported": report.summary_counts.get("SupportedRepairs", 0),
        "experimental": report.summary_counts.get("ExperimentalFindings", 0),
        "review": report.summary_counts.get("ItemsRequiringReview", 0),
    }


def _repair_types(report: RunReport) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in report.diagnoses:
        label = (
            f"{item.classification.value} / "
            f"{item.representation_identifier or 'Unidentified'} / "
            f"{item.representation_type or 'Unspecified'}"
        )
        result[label] = result.get(label, 0) + 1
    return result


def _element_scope(report: RunReport) -> str:
    return ", ".join(report.element_type_counts) or "No configured product scope"


def _element_statistics(report: RunReport) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for product_type, counts in report.element_type_counts.items():
        rows.append((
            product_type,
            (
                f"{counts.get('elements_scanned', 0):,} elements; "
                f"{counts.get('affected_representations', 0):,} issues; "
                f"{counts.get('automatically_repairable', 0):,} safe"
            ),
        ))
    return rows


def _version1_element_breakdown(report: RunReport) -> list[tuple[str, str]]:
    """Stable user breakdown with future direct-product classes grouped."""
    known = ("IfcSlab", "IfcOpeningElement", "IfcCovering")
    rows: list[tuple[str, str]] = []
    for product_type in known:
        values = report.element_type_counts.get(product_type, {})
        rows.append((product_type, f"{values.get('affected_representations', 0):,}"))
    other = sum(
        values.get("affected_representations", 0)
        for product_type, values in report.element_type_counts.items()
        if product_type not in known
    )
    rows.append(("Other direct-product classes", f"{other:,}"))
    return rows


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
            "classification": item.classification.value,
            "confidence_level": item.confidence_level.value,
            "usage_count": item.usage_count,
            "ultimate_product_count": item.ultimate_product_count,
            "ultimate_product_classes": item.ultimate_product_classes,
            "schema_status": item.schema_status,
            "rendering_risk": item.rendering_risk,
            "downstream_processing_risk": item.downstream_processing_risk,
            "repair_priority": item.repair_priority,
            "proposed_action": item.proposed_action,
            "repair_signature": item.repair_signature,
            "safety_level": item.safety_level,
            "viewer_test_status": item.viewer_test_status,
            "production_enabled": item.production_enabled,
            "repair_decision_reason": item.repair_decision_reason,
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
        report_only_count = len(report.audit_findings)
        review_in_revit_count = counts["remaining"] + report_only_count
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
            Spacer(1, 5 * mm), Paragraph(
                "IFC+SG Repair Summary", styles["CoverSub"]
            ),
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
            (counts["affected"], "Geometry References Found"),
            (counts["repairable"], "Ready to Repair"),
            (counts["remaining"], "Supported Items Remaining"),
            ("VERIFIED" if verification_passed else "CHECK", "IFC Verification"),
        ]
        cards = Table(
            [[p(value, "KPI") for value, _ in kpis], [p(label, "KPILabel") for _, label in kpis]],
            colWidths=[45 * mm] * 4,
        )
        cards.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
        ]))
        outcome_rows = [
            [
                p("REPAIRED AND VERIFIED"),
                p(
                    f"{counts['repaired']:,} geometry reference(s) were changed "
                    "in the repaired IFC and passed targeted verification."
                ),
            ],
        ]
        if review_in_revit_count:
            outcome_rows.append([
                p("REVIEW IN REVIT - NO CHANGE APPLIED"),
                p(
                    f"{review_in_revit_count:,} item(s) are shown for review only: "
                    f"{counts['remaining']:,} unresolved geometry reference(s) and "
                    f"{report_only_count:,} additional audit observation(s)."
                ),
            ])
        outcome_guide = Table(outcome_rows, colWidths=[58 * mm, 122 * mm])
        outcome_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf3")),
            ("TEXTCOLOR", (0, 0), (0, 0), colors.HexColor("#067647")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d5dd")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]
        if review_in_revit_count:
            outcome_style.extend([
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#fffaeb")),
                ("TEXTCOLOR", (0, 1), (0, 1), colors.HexColor("#b54708")),
            ])
        outcome_guide.setStyle(TableStyle(outcome_style))
        story += [cards, Spacer(1, 5 * mm), outcome_guide, Spacer(1, 10 * mm),
                  Paragraph("File Information", styles["Heading2"]),
                  key_value([
                      ("Input IFC", Path(report.source).name),
                      (
                          "Output IFC",
                          Path(report.output).name if report.output else "Not written",
                      ),
                      ("Schema", report.schema or "Unknown"),
                      ("Input size", format_bytes(report.input_size)),
                      ("Output size", format_bytes(report.output_size)),
                      ("Duration", f"{_duration(report):.2f} seconds"),
                      ("Repair rule", report.active_rule_id),
                  ]),
                  Spacer(1, 5 * mm),
                  p(report.disclaimer, "Muted"),
                  PageBreak()]

        assessment = report.file_assessment
        if assessment:
            ifc_sg = assessment.ifc_sg
            story += section("IFC+SG File Assessment")
            story += [key_value([
                (
                    "IFC+SG identification",
                    ifc_sg.classification.value if ifc_sg else "Not assessed",
                ),
                (
                    "Likely authoring tool",
                    ifc_sg.likely_exporter if ifc_sg else "Unknown",
                ),
                ("Schema", assessment.schema or "Unknown"),
                ("Size category", assessment.size_category),
                ("Processing strategy", assessment.strategy.value),
                (
                    "Evidence",
                    "; ".join(ifc_sg.evidence) if ifc_sg else "Not recorded",
                ),
            ]), Spacer(1, 8 * mm)]

        story += section("Repair Scope")
        story += [key_value([
            ("Rule", report.active_rule_id), ("Rule version", report.active_rule_version),
            ("Element scope", _element_scope(report)),
            (
                "Representations",
                "Body / SweptSolid, Body / Tessellation and FootPrint / Curve2D",
            ),
            (
                "Production ownership",
                "Direct IfcProductDefinitionShape ownership only",
            ),
            (
                "Excluded",
                "IfcShapeAspect and IfcRepresentationMap rules are disabled in "
                "Version 1 and were not scanned or modified",
            ),
        ]), PageBreak(), Paragraph("Performance Summary", styles["Section"])]
        performance = [
            ("Open IFC", report.durations.get("ifc_opening", 0.0)),
            ("Target elements", report.durations.get("collect_target_elements", 0.0)),
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
        classification_rows = [
            (
                name.replace("_", " ").title(),
                (
                    f"{values.get('detected', 0):,} detected; "
                    f"{values.get('repaired', 0):,} repaired; "
                    f"{values.get('remaining', values.get('detected', 0)):,} remaining"
                ),
            )
            for name, values in report.classification_counts.items()
            if values.get("detected", 0)
        ]
        type_rows = [(name, f"{count:,}") for name, count in _repair_types(report).items()]
        if not type_rows:
            type_rows = [("No targeted issues", "0")]
        audit_category_counts: dict[str, int] = {}
        for finding in report.audit_findings:
            audit_category_counts[finding.category] = (
                audit_category_counts.get(finding.category, 0) + 1
            )
        audit_rows = [
            (category, f"{count:,} - report only; no IFC change applied")
            for category, count in audit_category_counts.items()
        ] or [("Additional checks", "0")]
        story += [statistics_chart(), Spacer(1, 5 * mm), key_value([
            ("Geometry references found", f"{counts['affected']:,}"),
            ("Ready to repair", f"{counts['repairable']:,}"),
            ("Successfully repaired", f"{counts['repaired']:,}"),
            ("Remaining", f"{counts['remaining']:,}"),
        ] + _version1_element_breakdown(report)), Spacer(1, 10 * mm)]
        if report_only_count:
            story += [Paragraph("Report Only - Review in Revit", styles["Heading2"]),
                      key_value([
                          ("Total observations", f"{report_only_count:,}"),
                          ("IFC changes from these checks", "None"),
                      ] + audit_rows), Spacer(1, 10 * mm)]
        story += [Paragraph("Verification", styles["Heading2"]),
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
            p(
                "Detailed repair and report-only records are available in the HTML "
                "report. This tool does not replace the official submission validator."
            ),
            Spacer(1, 5 * mm),
            p(report.disclaimer, "Muted"),
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
            title=f"{APP_NAME} - IFC+SG Repair Report", author=APP_NAME,
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
        report_only_count = len(report.audit_findings)
        records_json = json.dumps(
            _records(report, self.cancelled), ensure_ascii=False
        ).replace("</", "<\\/")
        audit_groups_by_key: dict[tuple[str, ...], dict[str, object]] = {}
        for finding in report.audit_findings:
            key = (
                finding.category,
                finding.rule_id,
                finding.entity_type or "",
                finding.title,
                finding.detail,
                finding.submission_risk,
                finding.action,
            )
            group = audit_groups_by_key.get(key)
            if group is None:
                group = {
                    "group_id": len(audit_groups_by_key),
                    "category": finding.category,
                    "rule": finding.rule_id,
                    "entity_type": finding.entity_type or "",
                    "issue": finding.title,
                    "detail": finding.detail,
                    "submission_risk": finding.submission_risk,
                    "action": finding.action,
                    "entity_ids": [],
                    "count": 0,
                }
                audit_groups_by_key[key] = group
            entity_ids = group["entity_ids"]
            assert isinstance(entity_ids, list)
            entity_ids.append(finding.entity_step_id)
            group["count"] = int(group["count"]) + 1
        audit_groups = list(audit_groups_by_key.values())
        audit_groups_json = json.dumps(
            audit_groups, ensure_ascii=False, separators=(",", ":")
        ).replace("</", "<\\/")
        stage_rows = "".join(
            f"<tr><td>{html_escape(key.replace('_', ' ').title())}</td><td>{value:.3f} s</td></tr>"
            for key, value in report.durations.items()
        ) or "<tr><td colspan='2'>No stage timings recorded</td></tr>"
        type_rows = "".join(
            f"<div class='bar-row'><span>{html_escape(name)}</span><div class='bar'><i style='width:{(count / max(1, counts['affected'])) * 100:.1f}%'></i></div><b>{count:,}</b></div>"
            for name, count in _repair_types(report).items()
        ) or "<p class='muted'>No targeted repair types detected.</p>"
        element_rows = "".join(
            (
                f"<tr><td>{html_escape(product_type)}</td>"
                f"<td>{values.get('elements_scanned', 0):,}</td>"
                f"<td>{values.get('affected_representations', 0):,}</td>"
                f"<td>{values.get('automatically_repairable', 0):,}</td>"
                f"<td>{values.get('successfully_repaired', 0):,}</td></tr>"
            )
            for product_type, values in report.element_type_counts.items()
        ) or "<tr><td colspan='5'>No element policy statistics recorded</td></tr>"
        classification_rows = "".join(
            (
                f"<tr><td>{html_escape(name.replace('_', ' ').title())}</td>"
                f"<td>{values.get('detected', 0):,}</td>"
                f"<td>{values.get('high_confidence', 0):,}</td>"
                f"<td>{values.get('auto_repair', 0):,}</td>"
                f"<td>{values.get('repaired', 0):,}</td>"
                f"<td>{values.get('remaining', values.get('detected', 0)):,}</td></tr>"
            )
            for name, values in report.classification_counts.items()
            if values.get("detected", 0)
        ) or "<tr><td colspan='6'>No missing contexts detected</td></tr>"
        compatibility_rows = "".join(
            (
                f"<tr><td>{html_escape(str(item.get('signature', '')))}</td>"
                f"<td>{html_escape(str(item.get('safety_level', '')))}</td>"
                f"<td>{html_escape(str(item.get('internal_verification', '')))}</td>"
                f"<td>{html_escape(str(item.get('corenet_x_viewer', '')))}</td>"
                f"<td>{'Enabled' if item.get('production_enabled') else 'Disabled'}</td>"
                f"<td>{html_escape(str(item.get('reason', '')))}</td></tr>"
            )
            for item in report.repair_signature_statuses
        ) or "<tr><td colspan='6'>No signature policy was recorded</td></tr>"
        assessment = report.file_assessment
        ifc_sg = assessment.ifc_sg if assessment else None
        assessment_evidence = "".join(
            f"<li>{html_escape(item)}</li>"
            for item in (
                (ifc_sg.evidence + ifc_sg.warnings) if ifc_sg else []
            )
        ) or "<li>No IFC+SG identification evidence recorded</li>"

        def audit_section(section_id: str, title: str, category: str) -> str:
            findings = [
                item for item in report.audit_findings
                if item.category == category
            ]
            group_count = sum(
                group["category"] == category for group in audit_groups
            )
            return (
                f"<section id='{section_id}' class='audit-section' "
                f"data-audit-category='{html_escape(category)}'>"
                f"<h2>{html_escape(title)} "
                "<span class='status-badge report'>REPORT ONLY - REVIEW IN REVIT</span>"
                "</h2>"
                f"<div class='card audit-summary'><strong>{len(findings):,}</strong> "
                f"finding(s), condensed into <strong>{group_count:,}</strong> "
                "issue group(s). <strong>No IFC change was applied for these "
                "findings.</strong> Expand a group to inspect entity STEP IDs in "
                "batches of 50.</div>"
                "<div class='card'><div class='table-wrap'><table><thead><tr>"
                "<th>Rule</th><th>Findings</th><th>Entities</th><th>Issue</th><th>Detail</th>"
                "<th>CORENET X relevance</th><th>Action</th></tr></thead>"
                f"<tbody id='{section_id}-rows'></tbody></table></div>"
                "<div class='audit-table-controls'>"
                f"<label>Groups per page <select id='{section_id}-page-size'>"
                "<option>10</option><option selected>25</option><option>50</option>"
                "</select></label>"
                f"<div class='pager'><button id='{section_id}-prev'>Previous</button>"
                f"<span id='{section_id}-page'></span>"
                f"<button id='{section_id}-next'>Next</button></div>"
                "</div></div></section>"
            )

        audit_sections = "".join((
            audit_section("space-geometry", "Space Geometry", "Space Geometry"),
            audit_section(
                "quantity-information", "Quantity Information", "Quantity Information"
            ),
            audit_section("georeferencing", "Georeferencing", "Georeferencing"),
        ))
        if not report.audit_findings:
            audit_sections = ""
        report_only_nav = (
            '<a href="#additional-checks">Items to Review</a>'
            if report_only_count else ""
        )
        additional_checks_section = (
            '<section id="additional-checks"><h2>Report-Only Checks '
            '<span class="status-badge report">REVIEW IN REVIT</span></h2>'
            f'<div class="card review-card"><strong>{report_only_count:,}</strong> '
            'observation(s) from space geometry, quantity information and '
            'georeferencing. These checks did not modify the IFC. Repeated '
            'observations are grouped below.</div></section>'
            if report_only_count else ""
        )

        def category_section(
            section_id: str, title: str, classifications: set[str],
        ) -> str:
            selected = [
                item for item in report.diagnoses
                if item.classification.value in classifications
            ]
            high = sum(
                item.confidence_level.value == "HIGH" for item in selected
            )
            repaired = sum(item.repaired for item in selected)
            return (
                f"<section id='{section_id}'><h2>{html_escape(title)}</h2>"
                f"<div class='grid category-grid'>"
                f"<div class='card kpi'><strong>{len(selected):,}</strong><span>Detected</span></div>"
                f"<div class='card kpi'><strong>{high:,}</strong><span>High confidence</span></div>"
                f"<div class='card kpi'><strong>{repaired:,}</strong><span>Repaired</span></div>"
                f"<div class='card kpi'><strong>{len(selected)-repaired:,}</strong><span>Remaining</span></div>"
                f"</div><div class='card category-note'>Use Repair Records and the "
                f"Classification filter to inspect every record, candidate context, "
                f"confidence level, evidence and proposed action.</div></section>"
            )

        # Version 1's ordinary report is deliberately limited to direct-product
        # findings. The classification table and repair records already provide
        # the full supported breakdown, so do not render empty future-category
        # panels for ShapeAspect or RepresentationMap rules.
        category_sections = ""
        warnings = list(report.errors) + [issue.message for issue in report.validation_after]
        warnings_html = "".join(f"<li>{html_escape(item)}</li>" for item in warnings) or "<li>None recorded</li>"
        skipped_rules_html = "".join(
            f"<li><code>{html_escape(rule_id)}</code>: {html_escape(reason)}</li>"
            for rule_id, reason in sorted(report.skipped_rules.items())
        ) or "<li>None</li>"
        verification = "PASS" if report.targeted_verification.get("passed") else "NOT COMPLETED"
        unresolved_review_nav = (
            '<a href="#items-review">Unresolved Geometry</a>'
            if counts["remaining"] else ""
        )
        unresolved_review_section = (
            '<section id="items-review"><h2>Unresolved Geometry '
            '<span class="status-badge report">NO IFC CHANGE APPLIED</span></h2>'
            '<div class="card review-card"><strong>'
            f'{counts["remaining"]:,}</strong> geometry reference(s) could not be '
            'repaired automatically. Review these specific geometry items in Revit.'
            '</div></section>'
            if counts["remaining"] else ""
        )
        html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{APP_NAME} - Detailed Report</title>
<style>
:root{{--bg:#f3f6fa;--card:#fff;--text:#172033;--muted:#64748b;--line:#dce3ec;--blue:#155eef;--green:#067647;--green-bg:#ecfdf3;--amber:#b54708;--amber-bg:#fffaeb;--soft:#eef4ff;--shadow:0 4px 18px #17203312}}
[data-theme=dark]{{--bg:#0f1722;--card:#172334;--text:#edf2f7;--muted:#a3afc0;--line:#34445a;--blue:#79a8ff;--green:#70d384;--green-bg:#173b2a;--amber:#fdb022;--amber-bg:#443414;--soft:#203552;--shadow:none}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Segoe UI",Arial,sans-serif}}button,input,select{{font:inherit}}pre{{white-space:pre-wrap;word-break:break-word;font-size:12px}}
header{{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:14px 4vw;display:flex;align-items:center;gap:18px}}header h1{{font-size:18px;margin:0;white-space:nowrap}}header .grow{{flex:1}}.app-version{{display:inline-block;margin-left:6px;padding:2px 7px;border-radius:999px;background:var(--soft);color:var(--blue);font-size:11px;vertical-align:middle}}button{{border:1px solid var(--line);border-radius:7px;background:var(--card);color:var(--text);padding:8px 12px;cursor:pointer}}button:hover{{border-color:var(--blue)}}
nav{{display:flex;gap:4px;overflow:auto;padding:9px 4vw;background:var(--card);border-bottom:1px solid var(--line)}}nav a{{white-space:nowrap;color:var(--muted);text-decoration:none;padding:7px 11px;border-radius:6px}}nav a:hover{{background:var(--soft);color:var(--blue)}}
main{{max-width:1440px;margin:auto;padding:24px 4vw 60px}}section{{scroll-margin-top:105px;margin-bottom:24px}}h2{{font-size:19px;margin:0 0 12px}}h3{{font-size:14px;margin:18px 0 8px}}.grid{{display:grid;grid-template-columns:repeat(5,minmax(145px,1fr));gap:12px}}.category-grid{{grid-template-columns:repeat(4,minmax(145px,1fr))}}.category-note{{margin-top:12px;color:var(--muted)}}.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;box-shadow:var(--shadow)}}.kpi strong{{display:block;font-size:25px}}.kpi span,.muted{{color:var(--muted)}}.pass{{color:var(--green)}}.outcome-callouts{{display:grid;grid-template-columns:repeat(4,minmax(190px,1fr));gap:12px;margin:14px 0}}.outcome-card{{border:1px solid var(--line);border-radius:11px;padding:16px;background:var(--card)}}.outcome-card.fixed{{background:var(--green-bg);border-color:#abefc6}}.outcome-card.review{{background:var(--amber-bg);border-color:#fedf89}}.outcome-card strong{{display:block;font-size:28px;margin:7px 0 2px}}.outcome-card h3{{font-size:14px;margin:0 0 5px}}.outcome-card p{{color:var(--muted);margin:0;font-size:12px}}.status-badge{{display:inline-block;border-radius:999px;padding:3px 8px;font-size:10px;font-weight:800;letter-spacing:.03em;vertical-align:middle;white-space:nowrap}}.status-badge.fixed{{color:var(--green);background:var(--green-bg);border:1px solid #abefc6}}.status-badge.report{{color:var(--amber);background:var(--amber-bg);border:1px solid #fedf89}}.review-card{{background:var(--amber-bg);border-color:#fedf89}}.fixed-card{{background:var(--green-bg);border-color:#abefc6}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}dl{{display:grid;grid-template-columns:160px 1fr;gap:8px;margin:0}}dt{{color:var(--muted)}}dd{{margin:0;overflow-wrap:anywhere}}.outcome-grid{{display:grid;grid-template-columns:150px minmax(360px,1fr);gap:24px;align-items:center;min-height:150px}}.outcome-bars{{min-width:0}}.bar-row{{display:grid;grid-template-columns:minmax(190px,230px) minmax(120px,1fr) 72px;gap:12px;align-items:center;margin:12px 0}}.bar-row b{{text-align:right;font-variant-numeric:tabular-nums}}.bar{{height:9px;background:var(--soft);border-radius:9px;overflow:hidden}}.bar i{{display:block;height:100%;background:var(--blue)}}.donut{{width:112px;height:112px;border-radius:50%;margin:auto;background:conic-gradient(var(--green) 0 var(--repaired),#f59e0b var(--repaired) 100%);display:grid;place-items:center}}.donut:after{{content:attr(data-label);width:76px;height:76px;border-radius:50%;background:var(--card);display:grid;place-items:center;text-align:center;font-weight:700;line-height:1.2;white-space:pre-line}}
.tools{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}}input,select{{border:1px solid var(--line);border-radius:7px;background:var(--card);color:var(--text);padding:8px 10px}}input{{min-width:300px;flex:1}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:9px}}.record-top-scroll{{overflow-x:scroll;overflow-y:hidden;height:18px;margin-bottom:5px;border:1px solid var(--line);border-radius:7px;background:var(--soft);scrollbar-gutter:stable}}.record-top-scroll>div{{height:1px}}.record-table-wrap{{overflow-x:scroll;scrollbar-gutter:stable}}#recordsTable{{min-width:1420px}}#recordsTable th:nth-child(1){{width:110px}}#recordsTable th:nth-child(2){{width:110px}}#recordsTable th:nth-child(3){{width:210px}}#recordsTable th:nth-child(4){{width:150px}}#recordsTable th:nth-child(5){{min-width:260px}}#recordsTable th:nth-child(6){{width:190px}}#recordsTable th:nth-child(7){{min-width:300px}}table{{border-collapse:collapse;width:100%;background:var(--card)}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:9px 10px;vertical-align:top;white-space:nowrap}}th{{background:var(--soft);position:sticky;top:0}}th[data-sort]{{cursor:pointer;user-select:none}}th[data-sort]:hover{{color:var(--blue)}}.sort-indicator{{display:inline-block;width:14px;margin-left:5px;color:var(--muted);font-weight:700}}th[aria-sort="ascending"] .sort-indicator,th[aria-sort="descending"] .sort-indicator{{color:var(--blue)}}td.wrap{{white-space:normal;min-width:260px}}tr:hover td{{background:var(--soft)}}.pager{{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:10px}}code{{font-family:Consolas,monospace}}details{{border-top:1px solid var(--line);padding:10px 0}}.record-details{{border:0;padding:0}}.record-details summary{{cursor:pointer;color:var(--blue);font-weight:600}}.copy{{padding:2px 6px;font-size:12px}}footer{{color:var(--muted);text-align:center;padding:25px}}.audit-summary{{margin-bottom:10px;color:var(--muted)}}.audit-summary strong{{color:var(--text)}}.audit-table-controls{{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-top:10px}}.audit-table-controls label{{color:var(--muted)}}.audit-table-controls .pager{{margin-top:0}}.audit-section td:nth-child(4),.audit-section td:nth-child(5),.audit-section td:nth-child(6){{white-space:normal;min-width:220px}}.audit-entities{{min-width:260px}}.audit-entities details{{border:0;padding:0}}.audit-entities summary{{cursor:pointer;color:var(--blue);white-space:nowrap}}.entity-grid{{display:flex;flex-wrap:wrap;gap:5px;max-width:420px;margin:9px 0}}.entity-chip{{background:var(--soft);border-radius:5px;padding:3px 7px;font:12px Consolas,monospace}}.entity-pager{{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}}.entity-pager button{{padding:4px 7px;font-size:12px}}
@media(max-width:900px){{.grid,.category-grid,.outcome-callouts{{grid-template-columns:repeat(2,1fr)}}.two{{grid-template-columns:1fr}}.outcome-grid{{grid-template-columns:1fr}}dl{{grid-template-columns:120px 1fr}}.bar-row{{grid-template-columns:170px 1fr 65px}}}}
</style></head>
<body><header><h1>{APP_NAME}<span class="app-version">v{APP_VERSION}</span></h1><span class="muted">Repairs missing IfcShapeRepresentation context references in supported Revit 2025/2026 IFC+SG exports. This IFC4 schema non-compliance can cause elements to be missing during CORENET X model processing.</span><span class="grow"></span></header>
<nav><a href="#overview">Summary</a><a href="#records">Repairs Applied</a>{unresolved_review_nav}{report_only_nav}<a href="#verification">Verification</a><a href="#diagnostics">Technical Details</a></nav>
<main>
<section id="overview"><h2>Summary</h2><div class="card"><p>IFC+SG Repair Assistant helps BIM users detect and repair a known geometry-reference issue found in IFC+SG files exported from Autodesk Revit 2025 and Revit 2026.</p><p>The application restores missing IFC geometry references without changing the model geometry, helping prepare the IFC for the next stage of CORENET X submission.</p></div>
<div class="outcome-callouts">
<div class="outcome-card fixed"><span class="status-badge fixed">SUPPORTED</span><strong>{counts['affected']:,}</strong><h3>Direct product geometry references</h3><p>Version 1 scans supported direct-product ownership only.</p></div>
<div class="outcome-card fixed"><span class="status-badge fixed">READY</span><strong>{counts['repairable']:,}</strong><h3>Ready to repair</h3><p>Each correction has one unique compatible project context.</p></div>
<div class="outcome-card review"><span class="status-badge report">REMAINING</span><strong>{counts['remaining']:,}</strong><h3>Supported items remaining</h3><p>No automatic change is applied where the correction cannot be proven.</p></div>
<div class="outcome-card {'fixed' if verification == 'PASS' else 'review'}"><span class="status-badge {'fixed' if verification == 'PASS' else 'report'}">{'VERIFIED' if verification == 'PASS' else 'CHECK REQUIRED'}</span><strong>{'PASS' if verification == 'PASS' else '—'}</strong><h3>IFC verification</h3><p>{'All applied repairs passed targeted verification.' if verification == 'PASS' else 'Repair verification was not completed.'}</p></div>
</div>
<div class="grid">
<div class="card kpi"><strong>{counts['elements_scanned']:,}</strong><span>Elements scanned</span></div>
<div class="card kpi"><strong>{counts['elements_affected']:,}</strong><span>Affected elements</span></div>
<div class="card kpi"><strong>{counts['repaired']:,}</strong><span>Representations repaired</span></div>
<div class="card kpi"><strong>{counts['remaining']:,}</strong><span>Remaining issues</span></div>
<div class="card kpi"><strong class="{'pass' if verification == 'PASS' else ''}">{verification}</strong><span>Targeted verification</span></div></div>
<div class="two" style="margin-top:14px"><div class="card"><h3>File information</h3><dl>
<dt>Input IFC</dt><dd>{html_escape(Path(report.source).name)}</dd><dt>Output IFC</dt><dd>{html_escape(Path(report.output).name if report.output else 'Not written')}</dd>
<dt>Schema</dt><dd>{html_escape(report.schema or 'Unknown')}</dd><dt>Input size</dt><dd>{format_bytes(report.input_size)}</dd><dt>Output size</dt><dd>{format_bytes(report.output_size)}</dd><dt>Total duration</dt><dd>{_duration(report):.3f} seconds</dd></dl></div>
<div class="card"><h3>Repair scope</h3><dl><dt>Rule</dt><dd>{html_escape(report.active_rule_id)}</dd><dt>Version</dt><dd>{html_escape(report.active_rule_version)}</dd><dt>Mode</dt><dd>{html_escape(report.repair_mode or 'Audit')}</dd><dt>Version 1 repair</dt><dd>Direct product Body / SweptSolid, Body / Tessellation and FootPrint / Curve2D representations only.</dd><dt>Outside Version 1</dt><dd>Missing geometry references under IfcShapeAspect and IfcRepresentationMap were not scanned or modified.</dd></dl></div></div></section>
<section id="file-assessment"><h2>IFC+SG File Assessment</h2><div class="two">
<div class="card"><dl><dt>Classification</dt><dd>{html_escape(ifc_sg.classification.value if ifc_sg else 'Not assessed')}</dd><dt>Likely authoring tool</dt><dd>{html_escape(ifc_sg.likely_exporter if ifc_sg else 'Unknown')}</dd><dt>Schema</dt><dd>{html_escape(assessment.schema if assessment and assessment.schema else report.schema or 'Unknown')}</dd><dt>File size category</dt><dd>{html_escape(assessment.size_category if assessment else 'Not assessed')}</dd><dt>Processing strategy</dt><dd>{html_escape(assessment.strategy.value if assessment else 'Not assessed')}</dd></dl></div>
<div class="card"><h3>Evidence and warnings</h3><ul>{assessment_evidence}</ul></div></div></section>
<section id="statistics"><h2>Repair Statistics</h2><div class="two"><div class="card"><h3>Repair outcome</h3><div class="outcome-grid"><div class="donut" style="--repaired:{counts['repaired']/max(1,counts['affected'])*100:.1f}%" data-label="{counts['repaired']:,}&#10;fixed"></div><div class="outcome-bars">
<div class="bar-row"><span>Automatically repairable</span><div class="bar"><i style="width:{counts['repairable']/max(1,counts['affected'])*100:.1f}%"></i></div><b>{counts['repairable']:,}</b></div>
<div class="bar-row"><span>Repaired</span><div class="bar"><i style="width:{counts['repaired']/max(1,counts['affected'])*100:.1f}%"></i></div><b>{counts['repaired']:,}</b></div>
<div class="bar-row"><span>Remaining</span><div class="bar"><i style="width:{counts['remaining']/max(1,counts['affected'])*100:.1f}%"></i></div><b>{counts['remaining']:,}</b></div></div></div></div>
<div class="card"><h3>Representation types</h3>{type_rows}</div></div>
<div class="card" style="margin-top:14px"><h3>Element policy breakdown</h3>
<div class="table-wrap"><table><thead><tr><th>Element</th><th>Scanned</th><th>Issues</th><th>Safe</th><th>Repaired</th></tr></thead><tbody>{element_rows}</tbody></table></div></div></section>
<section id="classification"><h2>Classification</h2><div class="card"><div class="table-wrap"><table><thead><tr><th>Classification</th><th>Detected</th><th>High confidence</th><th>Proposed auto-repair</th><th>Repaired</th><th>Remaining</th></tr></thead><tbody>{classification_rows}</tbody></table></div></div></section>
{category_sections}
{unresolved_review_section}
{additional_checks_section}
{audit_sections}
<section id="records"><h2>Geometry Repair Records <span class="status-badge fixed">REPAIRED RECORDS ARE GREEN</span></h2><div class="card fixed-card" style="margin-bottom:10px"><strong>{counts['repaired']:,}</strong> record(s) were repaired in the output IFC. Records that were not changed are marked <span class="status-badge report">REVIEW IN REVIT</span>.</div><div class="card"><div class="tools"><input id="search" placeholder="Search STEP ID, GlobalId, element or name"><select id="elementFilter"><option value="">All elements</option></select><select id="representationFilter"><option value="">All representations</option></select><button id="csv">Export filtered CSV</button></div>
<div id="recordsTopScroll" class="record-top-scroll" aria-label="Top horizontal table scrollbar"><div id="recordsTopScrollInner"></div></div><div id="recordsTableWrap" class="table-wrap record-table-wrap"><table id="recordsTable"><thead><tr><th data-sort="outcome" aria-sort="none">Outcome<span class="sort-indicator">&#8597;</span></th><th data-sort="step_id" aria-sort="ascending">STEP ID<span class="sort-indicator">&#8593;</span></th><th data-sort="global_id" aria-sort="none">GlobalId<span class="sort-indicator">&#8597;</span></th><th data-sort="element" aria-sort="none">Element<span class="sort-indicator">&#8597;</span></th><th data-sort="name" aria-sort="none">Name<span class="sort-indicator">&#8597;</span></th><th data-sort="representation" aria-sort="none">Representation<span class="sort-indicator">&#8597;</span></th><th data-sort="details" aria-sort="none">Details<span class="sort-indicator">&#8597;</span></th></tr></thead><tbody id="rows"></tbody></table></div><div class="pager"><button id="prev">Previous</button><span id="page"></span><button id="pageNext">Next</button></div></div></section>
<section id="performance"><h2>Performance</h2><div class="two"><div class="card"><h3>Execution timeline</h3><table><tbody>{stage_rows}</tbody></table></div><div class="card"><h3>Duration comparison</h3>{''.join(f'''<div class="bar-row"><span>{html_escape(k.replace('_',' ').title())}</span><div class="bar"><i style="width:{v/max(.001,_duration(report))*100:.1f}%"></i></div><b>{v:.2f}s</b></div>''' for k,v in report.durations.items())}</div></div></section>
<section id="verification"><h2>Verification</h2><div class="two"><div class="card"><h3>Targeted output verification</h3><dl><dt>Result</dt><dd>{verification}</dd><dt>Intended changes</dt><dd>{report.targeted_verification.get('intended', 0)}</dd><dt>Verified changes</dt><dd>{report.targeted_verification.get('verified', 0)}</dd><dt>Targeted issues remaining</dt><dd>{report.targeted_verification.get('remaining', counts['remaining'])}</dd></dl></div><div class="card"><h3>Unexpected-change audit</h3><dl><dt>Expected modified records</dt><dd>{report.change_audit.get('expected_modified_records', 'Not run')}</dd><dt>Actual modified records</dt><dd>{report.change_audit.get('actual_modified_records', 'Not run')}</dd><dt>Unexpected records</dt><dd>{report.change_audit.get('unexpected_modified_records', 'Not run')}</dd></dl></div></div></section>
<section id="diagnostics"><h2>Technical Details</h2><div class="two"><div class="card"><h3>Warnings and exceptions</h3><ul>{warnings_html}</ul><h3>Verification messages</h3><ul>{''.join(f'<li>{html_escape(str(m))}</li>' for m in report.targeted_verification.get('messages', [])) or '<li>None recorded</li>'}</ul><h3>Skipped rules</h3><ul>{skipped_rules_html}</ul></div><div class="card"><h3>Execution details</h3><dl><dt>Temporary output</dt><dd>{'Cleaned up' if not report.temporary_path else 'Internal temporary file used'}</dd><dt>Output size</dt><dd>{format_bytes(report.output_size)}</dd><dt>Selected rules</dt><dd>{html_escape(', '.join(report.selected_rules) or 'None')}</dd><dt>Skipped rules</dt><dd>{len(report.skipped_rules):,}</dd><dt>Full validation</dt><dd>{'Performed' if report.full_validation_performed else 'Not requested'}</dd><dt>Expected changed records</dt><dd>{report.change_audit.get('expected_modified_records','Not run')}</dd><dt>Actual changed records</dt><dd>{report.change_audit.get('actual_modified_records','Not run')}</dd><dt>Unexpected changes</dt><dd>{report.change_audit.get('unexpected_modified_records','Not run')}</dd><dt>Write throughput</dt><dd>{format_bytes(int(report.system_diagnostics.get('write_throughput_bytes_per_second') or 0))}/s</dd><dt>Peak working set</dt><dd>{format_bytes(int(report.system_diagnostics.get('process_peak_working_set_bytes') or 0))}</dd><dt>Disk free</dt><dd>{format_bytes(int(report.system_diagnostics.get('disk_free_bytes') or report.system_diagnostics.get('available_free_bytes') or 0))}</dd></dl></div></div></section>
<section id="settings"><h2>Settings</h2><div class="card"><dl><dt>Application</dt><dd>{APP_NAME} v{APP_VERSION}</dd><dt>Rule</dt><dd>{html_escape(report.active_rule_id)} v{html_escape(report.active_rule_version)}</dd><dt>Repair mode</dt><dd>{html_escape(report.repair_mode or 'Scan only')}</dd><dt>Python</dt><dd>{html_escape(report.environment.get('python_version','Unknown'))}</dd><dt>IfcOpenShell</dt><dd>{html_escape(report.environment.get('ifcopenshell_version','Unknown'))}</dd></dl></div></section>
</main><footer>{html_escape(report.disclaimer)}<br>Generated by {APP_NAME} v{APP_VERSION} | {html_escape(report.finished_at or '')}</footer>
<script>const records={records_json};const auditGroups={audit_groups_json};let filtered=[...records],page=1,sortKey='step_id',ascending=true;const pageSize=50;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const copy=v=>navigator.clipboard?navigator.clipboard.writeText(String(v??'')):void 0;
const outcome=r=>r.repaired?'Repaired':r.safety_level==='Experimental'?'Experimental':'Review only';
const detailsText=r=>`Repair type: ${{r.representation||'-'}}; Result: ${{r.verification||r.status||'-'}}; Evidence: ${{r.evidence||'-'}}`;
const sortValue=(r,key)=>key==='outcome'?outcome(r):key==='details'?detailsText(r):(r[key]??'');
function options(id,key){{const el=document.getElementById(id);[...new Set(records.map(r=>r[key]).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b))).forEach(v=>el.insertAdjacentHTML('beforeend',`<option value="${{esc(v)}}">${{esc(v)}}</option>`))}}options('elementFilter','element');options('representationFilter','representation');
function updateSortIndicators(){{document.querySelectorAll('#recordsTable th[data-sort]').forEach(h=>{{const active=h.dataset.sort===sortKey;h.setAttribute('aria-sort',active?(ascending?'ascending':'descending'):'none');h.querySelector('.sort-indicator').textContent=active?(ascending?'\u2191':'\u2193'):'\u2195'}})}}
function sortRecords(){{filtered.sort((a,b)=>{{let x=sortValue(a,sortKey),y=sortValue(b,sortKey);if(typeof x==='string')x=x.toLocaleLowerCase();if(typeof y==='string')y=y.toLocaleLowerCase();return(x>y?1:x<y?-1:0)*(ascending?1:-1)}});updateSortIndicators()}}
function apply(){{const q=document.getElementById('search').value.trim().toLocaleLowerCase(),element=document.getElementById('elementFilter').value,representation=document.getElementById('representationFilter').value;filtered=records.filter(r=>{{const searchable=[r.step_id,r.global_id,r.element,r.name,r.representation,r.evidence].join(' ').toLocaleLowerCase();return(!q||searchable.includes(q))&&(!element||r.element===element)&&(!representation||r.representation===representation)}});sortRecords();page=1;render()}}
function syncRecordScrollWidth(){{const wrap=document.getElementById('recordsTableWrap'),top=document.getElementById('recordsTopScroll'),inner=document.getElementById('recordsTopScrollInner');inner.style.width=`${{document.getElementById('recordsTable').scrollWidth}}px`;if(top.scrollLeft!==wrap.scrollLeft)top.scrollLeft=wrap.scrollLeft}}
function render(){{const pages=Math.max(1,Math.ceil(filtered.length/pageSize));page=Math.min(page,pages);const rows=filtered.slice((page-1)*pageSize,page*pageSize);document.getElementById('rows').innerHTML=rows.map((r,i)=>`<tr id="record-${{i}}"><td>${{r.repaired?'<span class="status-badge fixed">REPAIRED</span>':r.safety_level==='Experimental'?'<span class="status-badge report">EXPERIMENTAL</span>':'<span class="status-badge report">REVIEW ONLY</span>'}}</td><td><code>#${{esc(r.step_id)}}</code> <button class="copy" data-copy="${{esc(r.step_id)}}">Copy</button></td><td><code>${{esc(r.global_id)}}</code> <button class="copy" data-copy="${{esc(r.global_id)}}">Copy</button></td><td>${{esc(r.element)}}</td><td>${{esc(r.name)}}</td><td>${{esc(r.representation)}}</td><td class="wrap"><details class="record-details"><summary>View details</summary><b>Repair type:</b> ${{esc(r.representation)}}<br><b>Representation STEP ID:</b> #${{esc(r.representation_step_id)}}<br><b>Result:</b> ${{esc(r.verification||r.status)}}<br><b>Context reference:</b> ${{r.old_context==null?'Missing':'#'+esc(r.old_context)}} &rarr; ${{r.new_context==null?'No change':'#'+esc(r.new_context)}}<br><b>Representation items:</b> ${{esc(r.item_count)}} (${{esc(r.item_classes)}})<br><b>Evidence:</b> ${{esc(r.evidence)}}</details></td></tr>`).join('')||'<tr><td colspan="7">No matching repair records.</td></tr>';document.getElementById('page').textContent=`Page ${{page}} of ${{pages}} | ${{filtered.length}} records`;document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>copy(b.dataset.copy));requestAnimationFrame(syncRecordScrollWidth)}}
['search','elementFilter','representationFilter'].forEach(id=>document.getElementById(id).addEventListener(id==='search'?'input':'change',apply));document.querySelectorAll('#recordsTable th[data-sort]').forEach(h=>h.onclick=()=>{{ascending=sortKey===h.dataset.sort?!ascending:true;sortKey=h.dataset.sort;sortRecords();page=1;render()}});document.getElementById('prev').onclick=()=>{{page=Math.max(1,page-1);render()}};document.getElementById('pageNext').onclick=()=>{{page++;render()}};const topScroll=document.getElementById('recordsTopScroll'),bottomScroll=document.getElementById('recordsTableWrap');topScroll.addEventListener('scroll',()=>{{bottomScroll.scrollLeft=topScroll.scrollLeft}});bottomScroll.addEventListener('scroll',()=>{{topScroll.scrollLeft=bottomScroll.scrollLeft}});window.addEventListener('resize',syncRecordScrollWidth);
function download(name,type,text){{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{{type}}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}}
document.getElementById('csv').onclick=()=>{{const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"',columns=[['Outcome',r=>outcome(r)],['STEP ID',r=>r.step_id],['GlobalId',r=>r.global_id],['Element',r=>r.element],['Name',r=>r.name],['Representation',r=>r.representation],['Details',r=>detailsText(r)]];download('{html_escape(Path(report.source).stem)}_repair_records.csv','text/csv;charset=utf-8','\\ufeff'+[columns.map(c=>quote(c[0])).join(','),...filtered.map(r=>columns.map(c=>quote(c[1](r))).join(','))].join('\\r\\n'))}};
const auditStates={{}};
function renderAuditEntities(groupId,requestedPage=1){{const group=auditGroups[groupId],target=document.getElementById(`audit-entities-${{groupId}}`);if(!group||!target)return;const size=50,pages=Math.max(1,Math.ceil(group.entity_ids.length/size)),entityPage=Math.max(1,Math.min(requestedPage,pages)),ids=group.entity_ids.slice((entityPage-1)*size,entityPage*size);target.dataset.page=String(entityPage);target.innerHTML=`<div class="entity-grid">${{ids.map(id=>`<span class="entity-chip">${{id==null?'No STEP ID':'#'+esc(id)}}</span>`).join('')}}</div><div class="entity-pager"><button data-entity-prev="${{groupId}}">Previous</button><span>Entity page ${{entityPage}} of ${{pages}}</span><button data-entity-next="${{groupId}}">Next</button></div>`;target.querySelector('[data-entity-prev]').onclick=()=>renderAuditEntities(groupId,entityPage-1);target.querySelector('[data-entity-next]').onclick=()=>renderAuditEntities(groupId,entityPage+1)}}
function renderAuditSection(sectionId){{const section=document.getElementById(sectionId),state=auditStates[sectionId];if(!section||!state)return;const pages=Math.max(1,Math.ceil(state.groups.length/state.pageSize));state.page=Math.max(1,Math.min(state.page,pages));const visible=state.groups.slice((state.page-1)*state.pageSize,state.page*state.pageSize);document.getElementById(`${{sectionId}}-rows`).innerHTML=visible.map(group=>`<tr><td><code>${{esc(group.rule)}}</code></td><td><strong>${{group.count.toLocaleString()}}</strong></td><td class="audit-entities"><details data-audit-group="${{group.group_id}}"><summary>View ${{group.entity_ids.length.toLocaleString()}} entity ID(s)</summary><div id="audit-entities-${{group.group_id}}"></div></details></td><td>${{esc(group.issue)}}</td><td>${{esc(group.detail)}}</td><td>${{esc(group.submission_risk)}}</td><td><span class="status-badge report">REVIEW IN REVIT</span><br><span class="muted">No IFC change applied</span></td></tr>`).join('')||'<tr><td colspan="7">No findings in this category.</td></tr>';document.getElementById(`${{sectionId}}-page`).textContent=`Page ${{state.page}} of ${{pages}} | ${{state.groups.length}} groups`;section.querySelectorAll('details[data-audit-group]').forEach(detail=>detail.addEventListener('toggle',()=>{{if(detail.open)renderAuditEntities(Number(detail.dataset.auditGroup),1)}}))}}
document.querySelectorAll('.audit-section').forEach(section=>{{const sectionId=section.id,category=section.dataset.auditCategory;auditStates[sectionId]={{groups:auditGroups.filter(group=>group.category===category),page:1,pageSize:25}};document.getElementById(`${{sectionId}}-page-size`).onchange=event=>{{auditStates[sectionId].pageSize=Number(event.target.value);auditStates[sectionId].page=1;renderAuditSection(sectionId)}};document.getElementById(`${{sectionId}}-prev`).onclick=()=>{{auditStates[sectionId].page--;renderAuditSection(sectionId)}};document.getElementById(`${{sectionId}}-next`).onclick=()=>{{auditStates[sectionId].page++;renderAuditSection(sectionId)}};renderAuditSection(sectionId)}});
sortRecords();render();</script></body></html>"""
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
