from __future__ import annotations

import json
from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Callable

from .config import RepairConfig
from .models import RunReport
from .repair import repair_file
from .telemetry import Telemetry, emit


COMPATIBILITY_PROFILES = (
    (
        "direct_product_only",
        "DIRECT_PRODUCT_ONLY",
        "Production-safe direct product repairs only",
        "production",
    ),
    (
        "shapeaspect_sweptsolid",
        "TEST_SHAPEASPECT_SWEPTSOLID",
        "Direct product plus ShapeAspect / Body / SweptSolid",
        "compat_shapeaspect_sweptsolid",
    ),
    (
        "shapeaspect_tessellation",
        "TEST_SHAPEASPECT_TESSELLATION",
        "Direct product plus ShapeAspect / Body / Tessellation",
        "compat_shapeaspect_tessellation",
    ),
    (
        "representationmap_body",
        "TEST_REPRESENTATIONMAP_BODY",
        "Direct product plus RepresentationMap / Body",
        "compat_representationmap_body",
    ),
    (
        "representationmap_footprint",
        "TEST_FOOTPRINT",
        "Direct product plus RepresentationMap / FootPrint / Curve2D",
        "compat_footprint",
    ),
    (
        "all_experimental",
        "TEST_ALL_REPAIRS",
        "Direct product plus every internally eligible experimental category",
        "compat_all",
    ),
)


def _write_matrix(
    source: Path, rows: list[dict[str, object]], output_dir: Path
) -> tuple[Path, Path]:
    base = output_dir / f"{source.stem}_COMPATIBILITY_TEST_MATRIX"
    json_path = base.with_suffix(".json")
    html_path = base.with_suffix(".html")
    payload = {
        "source": source.name,
        "warning": (
            "These files are intended for controlled viewer testing. "
            "They are not approved production outputs."
        ),
        "outputs": rows,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['file']))}</td>"
        f"<td>{escape(str(row['category']))}</td>"
        f"<td>{escape(str(row['internal_verification']))}</td>"
        f"<td>{escape(str(row['corenet_x_viewer']))}</td>"
        f"<td>{escape(str(row['repairs']))}</td>"
        f"<td>{escape(str(row['status']))}</td>"
        "</tr>"
        for row in rows
    )
    html_path.write_text(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>IFC+SG Compatibility Test Matrix</title>
<style>body{{font:14px Arial;margin:32px;color:#172033}}h1{{font-size:24px}}
.warning{{padding:14px;background:#fff7e6;border:1px solid #f5b942;border-radius:8px}}
table{{border-collapse:collapse;width:100%;margin-top:20px}}th,td{{padding:9px;
border:1px solid #d0d5dd;text-align:left}}th{{background:#eef4ff}}</style></head>
<body><h1>IFC+SG Compatibility Test Matrix</h1>
<p class="warning">{escape(str(payload['warning']))}</p>
<p>Source: <strong>{escape(source.name)}</strong></p>
<table><thead><tr><th>Test file</th><th>Repair category</th>
<th>Internal verification</th><th>CORENET X Viewer</th>
<th>Repairs</th><th>Status</th></tr></thead><tbody>{table_rows}</tbody></table>
</body></html>""",
        encoding="utf-8",
    )
    return json_path, html_path


def generate_compatibility_test_outputs(
    config: RepairConfig,
    *,
    cancelled: Callable[[], bool] | None = None,
    telemetry: Telemetry | None = None,
) -> RunReport:
    """Generate isolated outputs without promoting any experimental rule."""
    source = config.source.resolve()
    output_dir = (config.output_dir or source.parent).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    reports: list[RunReport] = []
    rows: list[dict[str, object]] = []
    total = len(COMPATIBILITY_PROFILES)
    for position, (profile_id, suffix, description, mode) in enumerate(
        COMPATIBILITY_PROFILES, 1
    ):
        if cancelled and cancelled():
            break
        output = output_dir / f"{source.stem}_{suffix}.ifc"
        emit(
            telemetry,
            "compatibility_test_output",
            f"Generating compatibility test file {position} of {total}",
            current=position - 1,
            total=total,
            cancellable=True,
        )
        child_config = replace(
            config,
            output=output,
            output_dir=None,
            repair_mode=mode,
            replace_original_with_backup=False,
            create_backup=False,
            overwrite_output=False,
        )
        try:
            report = repair_file(
                child_config, cancelled=cancelled, telemetry=telemetry
            )
            reports.append(report)
            repaired = int(report.summary_counts.get("SuccessfullyRepaired", 0))
            verified = bool(
                report.targeted_verification.get("passed")
                and report.targeted_verification.get("semantic_reopen", {}).get(
                    "passed"
                )
                and report.change_audit.get("passed")
            )
            status = (
                "Generated and internally verified"
                if report.output and verified
                else "No eligible repairs" if not report.output
                else "Verification requires review"
            )
            rows.append({
                "profile_id": profile_id,
                "file": Path(report.output).name if report.output else output.name,
                "category": description,
                "internal_verification": "Passed" if verified else "Not completed",
                "corenet_x_viewer": "Pending",
                "repairs": repaired,
                "status": status,
                "report_paths": dict(report.report_paths),
            })
        except Exception as exc:
            rows.append({
                "profile_id": profile_id,
                "file": output.name,
                "category": description,
                "internal_verification": "Failed",
                "corenet_x_viewer": "Not Tested",
                "repairs": 0,
                "status": f"{type(exc).__name__}: {exc}",
                "report_paths": {},
            })
    matrix_json, matrix_html = _write_matrix(source, rows, output_dir)
    summary = reports[0] if reports else RunReport(source=str(source))
    summary.repair_mode = "Generate Compatibility Test Files"
    summary.generated_outputs = rows
    summary.report_paths["compatibility_matrix_json"] = str(matrix_json)
    summary.report_paths["compatibility_matrix_html"] = str(matrix_html)
    emit(
        telemetry,
        "compatibility_test_complete",
        "Compatibility test files complete",
        current=len(rows),
        total=total,
        cancellable=False,
    )
    return summary
