from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QScrollArea

from ifc_context_repair.models import (
    FileAssessment,
    IfcSgAssessment,
    IfcSgClassification,
    ProcessingStrategy,
    RunReport,
)
from ifc_context_repair.ui.main_window import MainWindow, WorkflowState


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "docs" / "screenshots"
SOURCE = ROOT / "validation-output" / "packaged-smoke-input.ifc"


def assessment(*, supported: bool = True) -> FileAssessment:
    return FileAssessment(
        original_name="Sample Project.ifc",
        working_name="Sample Project.ifc",
        input_kind="IFC",
        schema="IFC4" if supported else "IFC4X3",
        size_bytes=652_954_035,
        size_category="Large",
        strategy=ProcessingStrategy.HYBRID,
        ifc_sg=IfcSgAssessment(
            IfcSgClassification.LIKELY if supported else IfcSgClassification.UNSUPPORTED,
            likely_exporter="Autodesk Revit 2025" if supported else "Unknown",
        ),
    )


def result_report(*, supported: bool = True, repaired: bool = False) -> RunReport:
    ready = 8_926 if supported else 0
    experimental = 20_362 if supported else 0
    review = 16 if supported else 29_304
    report = RunReport(
        source=str(SOURCE),
        output=str(SOURCE.with_name("Sample Project_repaired.ifc")) if repaired else None,
        schema="IFC4" if supported else "IFC4X3",
        input_size=652_954_035,
        output_size=652_954_771 if repaired else 0,
        total_duration_seconds=71.0,
        summary_counts={
            "AffectedRepresentations": 29_304,
            "AutomaticallyRepairable": ready,
            "SupportedRepairs": ready,
            "ExperimentalFindings": experimental,
            "ItemsRequiringReview": review,
            "ReportOnlyFindings": review,
            "AmbiguousFindings": 0,
            "SuccessfullyRepaired": ready if repaired else 0,
            "TargetedIssuesRemaining": (
                experimental + review if repaired else 29_304
            ),
        },
        file_assessment=assessment(supported=supported),
        targeted_verification={
            "passed": repaired,
            "intended": ready if repaired else 0,
            "verified": ready if repaired else 0,
            "remaining": 0 if repaired else ready,
        },
        change_audit={
            "passed": repaired,
            "expected_modified_records": ready if repaired else 0,
            "actual_modified_records": ready if repaired else 0,
            "unexpected_modified_records": 0,
        },
        report_paths={
            "html": str(SCREENSHOTS / "Sample_Project_IFCSG_Repair_Report.html"),
            "pdf": str(SCREENSHOTS / "Sample_Project_IFCSG_Repair_Report.pdf"),
        },
    )
    return report


def capture(window: MainWindow, name: str, *, bottom: bool = False) -> None:
    app = QApplication.instance()
    assert app is not None
    app.processEvents()
    scroll = window.findChild(QScrollArea, "scroll")
    if scroll:
        bar = scroll.verticalScrollBar()
        bar.setValue(bar.maximum() if bottom else 0)
    app.processEvents()
    target = SCREENSHOTS / f"{name}.png"
    if not window.grab().save(str(target), "PNG"):
        raise RuntimeError(f"Could not save {target}")


def main() -> int:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1120, 930)
    window.show()

    window.reset()
    capture(window, "01-select-ifc")

    window._set_source(SOURCE)
    window.file_name.setText("Sample Project.ifc")
    window.file_meta.setText("622.7 MB  |  IFC4  |  Modified 27 Jul 2026, 12:59 PM")
    capture(window, "02-selected-ifc")

    window._apply_state(WorkflowState.SCANNING)
    window.progress_stage.setText("Checking IFC+SG geometry references")
    window.progress.setRange(0, 100)
    window.progress.setValue(46)
    window.progress_detail.setText("286.4 MB of 622.7 MB  •  46%  •  Elapsed 00:18")
    capture(window, "03-checking-ifc")

    report = result_report()
    window.report = report
    window._show_scan_results(report)
    window._apply_state(WorkflowState.ISSUES_FOUND)
    capture(window, "04-results-ready")

    unsupported = result_report(supported=False)
    window.report = unsupported
    window._show_scan_results(unsupported)
    window._apply_state(WorkflowState.ISSUES_FOUND)
    capture(window, "05-unsupported-file")

    window.report = report
    window._show_scan_results(report)
    window._apply_state(WorkflowState.REPAIRING)
    window.progress_stage.setText("Saving and verifying repaired IFC")
    window.progress.setRange(0, 100)
    window.progress.setValue(73)
    window.progress_detail.setText(
        "454.6 MB of 622.7 MB  •  73%  •  91.8 MB/s  •  Estimated remaining 00:03"
    )
    capture(window, "06-repairing-ifc")

    completed = result_report(repaired=True)
    window.operation = "repair"
    window._completed(completed)
    capture(window, "07-repair-completed", bottom=True)

    no_issues = result_report()
    no_issues.summary_counts.update({
        "AffectedRepresentations": 0,
        "AutomaticallyRepairable": 0,
        "ReportOnlyFindings": 0,
        "AmbiguousFindings": 0,
        "SupportedRepairs": 0,
        "ExperimentalFindings": 0,
        "ItemsRequiringReview": 0,
    })
    window.report = no_issues
    window._show_scan_results(no_issues)
    window._apply_state(WorkflowState.NO_ISSUES)
    capture(window, "08-no-issues-detected")

    window.repair_mode_audit.setChecked(True)
    audit = result_report()
    audit.repair_mode = "Audit Only"
    window.operation = "scan"
    window._completed(audit)
    capture(window, "09-audit-completed", bottom=True)

    window._apply_state(WorkflowState.FAILED)
    window._failed({
        "stage": "verification",
        "type": "VerificationError",
        "message": "An unexpected change was detected.",
        "temporary_file_removed": True,
    })
    capture(window, "10-repair-failed", bottom=True)

    window.repair_mode_compatibility.setChecked(True)
    compatibility = result_report()
    window.report = compatibility
    window._show_scan_results(compatibility)
    window._apply_state(WorkflowState.ISSUES_FOUND)
    capture(window, "11-compatibility-test-mode")

    compatibility.generated_outputs = [
        {
            "profile_id": "direct_product_only",
            "status": "Generated and internally verified",
        },
        {
            "profile_id": "shapeaspect_sweptsolid",
            "status": "Generated and internally verified",
        },
        {
            "profile_id": "shapeaspect_tessellation",
            "status": "Generated and internally verified",
        },
        {
            "profile_id": "representationmap_body",
            "status": "Generated and internally verified",
        },
        {
            "profile_id": "representationmap_footprint",
            "status": "Generated and internally verified",
        },
        {
            "profile_id": "all_experimental",
            "status": "Generated and internally verified",
        },
    ]
    compatibility.report_paths["compatibility_matrix_html"] = str(
        SCREENSHOTS / "Compatibility_Test_Matrix.html"
    )
    window.operation = "repair"
    window._completed(compatibility)
    capture(window, "12-compatibility-tests-completed", bottom=True)

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
