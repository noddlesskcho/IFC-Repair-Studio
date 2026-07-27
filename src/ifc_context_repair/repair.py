from __future__ import annotations

import os
import shutil
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import RepairConfig
from .change_audit import audit_targeted_changes
from .diagnostics import DiagnosticLogger, system_snapshot
from .errors import CancelledError, OutputError
from .models import (
    Diagnosis,
    IfcSgClassification,
    ProcessingStrategy,
    RunReport,
    Status,
)
from .indirect import is_repairable_in_mode
from .ifc_sg_assessment import build_file_assessment
from .naming import overwrite_backup_path
from .output_safety import cleanup_abandoned_temps, preflight_output
from .parser import check_step_envelope, open_model, require_ifcopenshell
from .reporting import write_html, write_pdf
from .prescan import profile_step
from .rules import ACTIVE_RULE, RuleScanResult
from .rules.ifc_sg import IFC_SG_RULES, IfcSgRuleContext
from .step_patch import apply_patch_plan, build_patch_plan, validate_patch_plan
from .target_verification import verify_step_envelope, verify_targeted_output
from .telemetry import StageUpdate, Telemetry, emit
from .validator import classify_issues, validate_schema

Progress = Callable[[str, int], None]


def _environment() -> dict[str, str]:
    import platform
    import sys

    ifcopenshell = require_ifcopenshell()
    return {
        "application_version": "1.0.0",
        "ifcopenshell_version": str(getattr(ifcopenshell, "version", "unknown")),
        "python_version": sys.version.split()[0],
        "operating_system": platform.platform(),
    }


def _selected(
    diagnoses: list[Diagnosis], include_warnings: bool,
    selected_step_ids: set[int] | None = None,
    minimum_confidence: float = 0.70,
    repair_mode: str = "safe",
) -> list[Diagnosis]:
    return [
        item for item in diagnoses
        if is_repairable_in_mode(item, repair_mode) and item.proposed_context
        and item.confidence >= minimum_confidence and (
            selected_step_ids is None
            or item.representation_step_id in selected_step_ids
        )
    ]


def _legacy_progress(
    progress: Progress | None, message: str, current: int | None, total: int | None,
    fallback: int,
) -> None:
    if not progress:
        return
    value = fallback
    if current is not None and total:
        value = max(0, min(100, int(current * 100 / total)))
    progress(message, value)


def _analyse_loaded(
    path: Path,
    *,
    validate: bool,
    quick: bool,
    cancelled: Callable[[], bool] | None,
    progress: Progress | None,
    telemetry: Telemetry | None = None,
    max_file_size_gb: float | None = None,
    repair_mode: str = "safe",
) -> tuple[RunReport, Any]:
    total_mark = time.perf_counter()
    started = datetime.now(timezone.utc)
    metadata_mark = time.perf_counter()
    stat = path.stat()
    report = RunReport(
        source=str(path.resolve()), started_at=started.isoformat(),
        environment=_environment(), input_size=stat.st_size,
        active_rule_id="IFCSG_RULE_REGISTRY_V1",
        active_rule_version="1.0",
        repair_mode=repair_mode.title(),
    )

    emit(telemetry, "input_metadata", "Reading input file metadata", current=1, total=1)
    report.durations["input_metadata"] = time.perf_counter() - metadata_mark
    if cancelled and cancelled():
        raise CancelledError("Scan cancelled before IFC opening")

    check_step_envelope(path, max_file_size_gb)
    emit(
        telemetry, "step_prescan",
        "Inspecting IFC schema and selecting applicable IFC+SG checks",
        bytes_processed=0, bytes_total=stat.st_size, cancellable=True,
    )
    mark = time.perf_counter()

    def prescan_progress(current: int, total: int) -> None:
        emit(
            telemetry, "step_prescan",
            "Inspecting IFC structure and known issue signatures",
            bytes_processed=current, bytes_total=total, cancellable=True,
        )

    profile = profile_step(
        path, cancelled=cancelled, progress=prescan_progress,
    )
    report.durations["step_prescan"] = time.perf_counter() - mark
    report.prescan_candidates = profile.candidates
    report.schema = profile.schema or "Unknown"
    report.file_assessment = build_file_assessment(path, profile)
    report.system_diagnostics.update({
        "processing_strategy": report.file_assessment.strategy.value,
        "size_category": report.file_assessment.size_category,
        "prescan_entity_counts": profile.entity_counts,
        "missing_context_signatures": profile.missing_context_signatures,
    })

    if (
        report.file_assessment.strategy is ProcessingStrategy.LIMITED_AUDIT
        or (profile.schema or "").upper() != "IFC4"
    ):
        reason = (
            f"This file uses {profile.schema or 'an unknown schema'}. The current "
            "repair rules are designed and tested for IFC+SG IFC4 files. "
            "No repair has been applied."
            if (profile.schema or "").upper() != "IFC4"
            else "Available resources require a streaming limited audit; semantic repair was skipped."
        )
        report.errors.append(reason)
        report.summary_counts = {
            "ElementsScanned": 0,
            "ElementsAffected": 0,
            "RepresentationsScanned": profile.entity_counts.get(
                "IFCSHAPEREPRESENTATION", 0
            ),
            "AffectedRepresentations": len(profile.candidates),
            "AutomaticallyRepairable": 0,
            "NotAutomaticallyRepairable": len(profile.candidates),
            "HighConfidenceRepairable": 0,
        }
        report.selected_rules = []
        report.skipped_rules = {
            rule.rule_id: reason for rule in IFC_SG_RULES.all()
        }
        report.rule_metadata = [rule.metadata() for rule in IFC_SG_RULES.all()]
        report.finished_at = datetime.now(timezone.utc).isoformat()
        report.total_duration_seconds = time.perf_counter() - total_mark
        emit(telemetry, "limited_audit_complete", "Limited structural audit complete",
             current=1, total=1)
        return report, None

    emit(
        telemetry, "ifc_opening", "Opening and parsing IFC", indeterminate=True,
        cancellable=False,
    )
    _legacy_progress(progress, "Opening and parsing IFC", None, None, 10)
    mark = time.perf_counter()
    model = open_model(path, max_file_size_gb)
    report.durations["ifc_opening"] = time.perf_counter() - mark
    if cancelled and cancelled():
        raise CancelledError("Operation cancelled after IFC parsing")
    report.schema = str(getattr(model, "schema", "unknown"))
    report.file_assessment = build_file_assessment(path, profile, model=model)

    try:
        file_name = model.header.file_name
        description = model.header.file_description
        report.exporter_header = {
            "name": str(file_name.name),
            "time_stamp": str(file_name.time_stamp),
            "preprocessor_version": str(file_name.preprocessor_version),
            "originating_system": str(file_name.originating_system),
            "authorization": str(file_name.authorization),
            "description": str(description.description),
            "implementation_level": str(description.implementation_level),
        }
    except Exception as exc:
        report.exporter_header = {"read_error": str(exc)}

    def rule_progress(stage_id: str, current: int, total: int) -> None:
        messages = {
            "collect_target_elements": "Collecting supported element targets",
            "collect_shape_representations": "Collecting directly owned shape representations",
            "context_index": "Building the semantic context index",
            "opening_relationships": "Checking opening-to-host relationships",
            "context_resolution": "Resolving representation contexts",
            "indirect_context_index": "Indexing project representation contexts",
            "indirect_product_ownership": "Indexing product ownership",
            "indirect_shape_aspects": "Indexing shape-aspect representations",
            "indirect_representation_index": "Indexing reusable mapped representations",
            "indirect_classification": "Classifying missing representation contexts",
        }
        message = messages.get(stage_id, "Preparing repair targets")
        emit(
            telemetry, stage_id, message, current=current, total=total,
            cancellable=True,
        )
        _legacy_progress(progress, message, current, total, 50)

    emit(
        telemetry, "collect_target_elements",
        "Collecting supported IFC+SG repair targets", current=0, total=1,
    )
    rule_mark = time.perf_counter()
    if profile.candidates:
        scan = ACTIVE_RULE.detect(
            model, timings=report.durations, progress=rule_progress,
            cancelled=cancelled, repair_mode=repair_mode,
        )
    else:
        scan = RuleScanResult(
            rule_id=ACTIVE_RULE.rule_id,
            rule_version=ACTIVE_RULE.version,
            diagnoses=[],
            targets=[],
            elements_scanned=len(model.by_type("IfcProduct")),
            elements_affected=0,
            representations_scanned=profile.entity_counts.get(
                "IFCSHAPEREPRESENTATION", 0
            ),
            type_counts={},
            classification_counts={},
        )
        report.skipped_rules.update({
            "DIRECT_PRODUCT_MISSING_CONTEXT_V2": "No missing ContextOfItems found",
            "SHAPE_ASPECT_PRODUCT_MISSING_CONTEXT_V1": "No missing ContextOfItems found",
            "REPRESENTATION_MAP_MISSING_CONTEXT_V1": "No missing ContextOfItems found",
            "REPRESENTATION_MAP_FOOTPRINT_MISSING_CONTEXT_V1": (
                "No missing ContextOfItems found"
            ),
        })
    rule_total = time.perf_counter() - rule_mark
    measured_rule_parts = sum(
        report.durations.get(key, 0.0)
        for key in (
            "collect_target_elements", "collect_shape_representations",
            "context_index", "opening_relationships", "context_resolution",
            "indirect_index_build", "indirect_classification",
        )
    )
    report.durations["repair_target_modeling"] = max(
        0.0, rule_total - measured_rule_parts
    )
    report.diagnoses = scan.diagnoses
    report.element_type_counts = scan.type_counts
    report.classification_counts = scan.classification_counts
    repairable = sum(target.automatically_repairable for target in scan.targets)
    report.summary_counts = {
        "ElementsScanned": scan.elements_scanned,
        "ElementsAffected": scan.elements_affected,
        "RepresentationsScanned": scan.representations_scanned,
        "AffectedRepresentations": len(scan.diagnoses),
        "AutomaticallyRepairable": repairable,
        "NotAutomaticallyRepairable": len(scan.diagnoses) - repairable,
        "HighConfidenceRepairable": sum(
            item.status is Status.SAFE and item.proposed_context is not None
            for item in scan.diagnoses
        ),
    }

    registry_context = IfcSgRuleContext(
        model=model,
        schema=report.schema or "",
        profile=profile,
        diagnoses=report.diagnoses,
    )
    selection = IFC_SG_RULES.select(registry_context)
    report.selected_rules = [rule.rule_id for rule in selection.selected]
    report.skipped_rules.update(selection.skipped)
    report.rule_metadata = [rule.metadata() for rule in IFC_SG_RULES.all()]
    for rule in selection.selected:
        if rule.repair_mode != "AUDIT_ONLY":
            continue
        mark = time.perf_counter()
        emit(
            telemetry, f"audit_{rule.rule_id.casefold()}",
            f"Running {rule.title}", indeterminate=True, cancellable=True,
        )
        try:
            report.audit_findings.extend(rule.detect(registry_context))
        except Exception as exc:
            report.errors.append(
                f"Optional audit rule {rule.rule_id} failed: {type(exc).__name__}: {exc}"
            )
            report.skipped_rules[rule.rule_id] = f"Rule failure: {exc}"
        report.durations[f"audit_{rule.rule_id.casefold()}"] = (
            time.perf_counter() - mark
        )
    report.summary_counts.update({
        "ReportOnlyFindings": len(report.audit_findings) + sum(
            not target.automatically_repairable for target in scan.targets
        ),
        "AmbiguousFindings": sum(
            item.status is Status.AMBIGUOUS for item in scan.diagnoses
        ),
    })

    if validate:
        emit(
            telemetry, "full_validation_before",
            "Running optional full IFC validation", indeterminate=True,
            cancellable=False,
        )
        _legacy_progress(progress, "Running full IFC validation", None, None, 75)
        mark = time.perf_counter()
        report.validation_before = validate_schema(model)
        report.durations["full_validation_before"] = time.perf_counter() - mark
        report.full_validation_performed = True

    report.finished_at = datetime.now(timezone.utc).isoformat()
    report.total_duration_seconds = time.perf_counter() - total_mark
    emit(telemetry, "scan_complete", "Scan complete", current=1, total=1)
    _legacy_progress(progress, "Scan complete", 1, 1, 100)
    return report, model


def analyse(
    path: Path,
    *,
    validate: bool = False,
    quick: bool = True,
    cancelled: Callable[[], bool] | None = None,
    progress: Progress | None = None,
    telemetry: Telemetry | None = None,
    repair_mode: str = "safe",
) -> RunReport:
    report, _ = _analyse_loaded(
        path.resolve(), validate=validate, quick=quick, cancelled=cancelled,
        progress=progress, telemetry=telemetry, repair_mode=repair_mode,
    )
    if repair_mode.casefold() == "audit":
        report_base = path.resolve().with_name(f"{path.stem}_IFCSG_Audit_Report")
        pdf_path = report_base.with_suffix(".pdf")
        html_path = report_base.with_suffix(".html")
        mark = time.perf_counter()
        emit(
            telemetry, "generate_pdf_report", "Generating PDF audit summary",
            indeterminate=True, cancellable=True,
        )
        write_pdf(report, pdf_path)
        report.durations["generate_pdf_report"] = time.perf_counter() - mark
        report.report_paths["pdf"] = str(pdf_path)
        if cancelled and cancelled():
            raise CancelledError("Audit cancelled after PDF generation")
        mark = time.perf_counter()
        emit(
            telemetry, "generate_html_report",
            "Generating HTML classification report",
            indeterminate=True, cancellable=True,
        )
        write_html(report, html_path, cancelled=cancelled)
        report.durations["generate_html_report"] = time.perf_counter() - mark
        report.report_paths["html"] = str(html_path)
        report.finished_at = datetime.now(timezone.utc).isoformat()
    return report


def repair_file(
    config: RepairConfig,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Progress | None = None,
    telemetry: Telemetry | None = None,
) -> RunReport:
    source = config.source.resolve()
    output = config.resolved_output()
    report: RunReport | None = None
    temporary: Path | None = None
    current_stage = "initialization"
    total_started = time.perf_counter()
    source_was_replaced = False

    diagnostic_log = output.with_name(f"{source.stem}_repair_debug.log")

    diagnostics = DiagnosticLogger(
        diagnostic_log, enabled=config.debug_logging, source=source, output=output,
    )

    def log_event(
        stage: str, status: str, *, duration: float | None = None,
        message: str = "", **extra: object,
    ) -> None:
        event = diagnostics.write(
            stage, status, duration=duration, message=message,
            temporary=temporary, **extra,
        )
        if report is not None:
            report.stage_events.append(event)

    def timed(stage: str, message: str, function: Callable[[], Any], **stage_kwargs: object) -> Any:
        nonlocal current_stage
        current_stage = stage
        emit(telemetry, stage, message, **stage_kwargs)
        mark = time.perf_counter()
        log_event(stage, "started", message=message)
        try:
            value = function()
        except Exception as exc:
            duration = time.perf_counter() - mark
            log_event(stage, "failed", duration=duration, message=str(exc))
            if report is not None:
                report.durations[stage] = duration
            raise
        duration = time.perf_counter() - mark
        log_event(stage, "completed", duration=duration, message=message)
        if report is not None:
            report.durations[stage] = duration
        return value

    try:
        log_event(
            "input_metadata", "completed", file_size=source.stat().st_size,
            modified_utc=datetime.fromtimestamp(
                source.stat().st_mtime, timezone.utc
            ).isoformat(), environment=_environment(),
        )
        report, model = _analyse_loaded(
            source, validate=config.full_validation, quick=not config.full_validation,
            cancelled=cancelled, progress=progress, telemetry=telemetry,
            max_file_size_gb=config.max_file_size_gb,
            repair_mode=config.repair_mode,
        )
        report.log_path = str(diagnostic_log) if config.debug_logging else None
        for analysis_stage in (
            "input_metadata", "ifc_opening", "collect_target_elements",
            "collect_shape_representations", "context_index", "opening_relationships",
            "context_resolution", "repair_target_modeling", "full_validation_before",
            "indirect_index_build", "indirect_classification",
        ):
            if analysis_stage in report.durations:
                log_event(
                    analysis_stage, "completed",
                    duration=report.durations[analysis_stage],
                    message="Instrumented analysis stage",
                    file_size=report.input_size,
                )
        selected = _selected(
            report.diagnoses, config.include_warnings, config.selected_step_ids,
            config.minimum_confidence, config.repair_mode,
        )
        if (
            report.file_assessment
            and report.file_assessment.prescan_counts.get("DUPLICATE_STEP_IDS", 0)
        ):
            raise OutputError(
                "Duplicate STEP IDs were detected. Repair output will not be published."
            )
        if not selected:
            report.errors.append("No automatically repairable target is available")
            return report
        if cancelled and cancelled():
            raise CancelledError("Repair cancelled before output creation")

        if output == source and not config.replace_original_with_backup:
            raise OutputError("Replacing the source requires explicit overwrite mode")
        if config.replace_original_with_backup and not config.create_backup:
            raise OutputError("Overwrite mode requires a backup")
        if output.exists() and output != source and not config.overwrite_output:
            raise OutputError(f"Output already exists: {output}")

        removed_temps = timed(
            "abandoned_temp_cleanup", "Checking for abandoned temporary outputs",
            lambda: cleanup_abandoned_temps(
                output.parent, older_than_hours=config.abandoned_temp_age_hours,
                output_stem=output.stem,
            ), current=1, total=1,
        )
        preflight = timed(
            "output_preflight", "Checking output safety and available disk space",
            lambda: preflight_output(
                source, output,
                replace_original=config.replace_original_with_backup,
                safety_factor=config.disk_safety_factor,
                safety_margin_mb=config.disk_safety_margin_mb,
            ), current=1, total=1,
        )
        report.system_diagnostics.update(preflight)
        report.system_diagnostics["abandoned_temp_files_removed"] = len(removed_temps)

        backup: Path | None = None
        if config.replace_original_with_backup:
            backup = overwrite_backup_path(source)
            timed(
                "backup_creation", "Copying untouched original to backup",
                lambda: shutil.copy2(source, backup), indeterminate=True,
                cancellable=False,
            )
            report.backup = str(backup)
        else:
            report.durations["backup_creation"] = 0.0
            log_event(
                "backup_creation", "skipped",
                message="Save As mode keeps the original unchanged",
            )

        replacements = timed(
            "build_patch_plan_inputs", f"Preparing {len(selected):,} targeted changes",
            lambda: {
                item.representation_step_id: item.proposed_context.step_id
                for item in selected if item.proposed_context
            }, current=len(selected), total=len(selected),
        )

        def plan_progress(current: int, total: int) -> None:
            emit(
                telemetry, "build_patch_plan",
                f"Building patch plan: {current:,} / {total:,}",
                current=current, total=total, cancellable=True,
            )

        patch_plan = timed(
            "build_patch_plan", f"Building patch plan for {len(replacements):,} changes",
            lambda: build_patch_plan(
                source, replacements, cancelled=cancelled, progress=plan_progress,
            ), current=0, total=len(replacements), cancellable=True,
        )
        timed(
            "validate_patch_plan", "Validating ordered non-overlapping patch plan",
            lambda: validate_patch_plan(patch_plan), current=len(replacements),
            total=len(replacements), cancellable=False,
        )
        temporary = output.with_name(
            f".{output.stem}.{uuid.uuid4().hex}.tmp.ifc"
        )
        report.temporary_path = str(temporary)
        timed(
            "create_temporary_output", "Preparing repaired IFC",
            lambda: temporary.open("xb").close(), current=1, total=1,
            temporary_path=temporary, cancellable=True,
        )
        write_started = time.perf_counter()

        def write_progress(
            bytes_done: int, bytes_total: int, patches_done: int, patches_total: int,
        ) -> None:
            elapsed = max(0.000001, time.perf_counter() - write_started)
            throughput = bytes_done / elapsed
            eta = (bytes_total - bytes_done) / throughput if throughput else None
            emit(
                telemetry, "apply_patches",
                f"Applying {patches_total:,} targeted changes",
                current=patches_done, total=patches_total,
                bytes_processed=bytes_done, bytes_total=bytes_total,
                elapsed_seconds=elapsed,
                throughput_bytes_per_second=throughput,
                estimated_remaining_seconds=eta,
                temporary_path=temporary, output_size=bytes_done, cancellable=True,
            )
            _legacy_progress(progress, "Saving repaired IFC", bytes_done, bytes_total, 0)

        write_result = timed(
            "apply_patches", f"Applying {len(replacements):,} targeted changes",
            lambda: apply_patch_plan(
                patch_plan, temporary, cancelled=cancelled, progress=write_progress,
            ),
            indeterminate=False, temporary_path=temporary, cancellable=True,
        )
        report.durations["apply_patches"] = write_result.write_seconds
        report.durations["flush_output"] = write_result.flush_seconds
        report.system_diagnostics.update({
            "bytes_processed": write_result.bytes_processed,
            "bytes_written": write_result.bytes_written,
            "write_throughput_bytes_per_second": write_result.throughput_bytes_per_second,
        })
        emit(
            telemetry, "flush_output", "Flushing repaired IFC safely to disk",
            current=1, total=1, bytes_processed=write_result.bytes_written,
            bytes_total=write_result.bytes_written, cancellable=False,
        )
        if cancelled and cancelled():
            raise CancelledError("Repair cancelled after temporary output was written")

        def check_size() -> int:
            if not temporary or not temporary.exists():
                raise OutputError("Temporary output was not created")
            size = temporary.stat().st_size
            if size <= 0:
                raise OutputError("Temporary output is empty")
            return size

        report.output_size = timed(
            "output_size_verification", "Checking temporary output size",
            check_size, current=1, total=1,
        )
        envelope = timed(
            "step_envelope_verification", "Verifying STEP header and footer",
            lambda: verify_step_envelope(temporary, patch_plan.expected_output_size),
            current=1, total=1,
        )
        def verify_progress(current: int, total: int) -> None:
            emit(
                telemetry, "targeted_verification",
                f"Verifying repaired records: {current:,} / {total:,}",
                current=current, total=total, cancellable=True,
            )

        verification = timed(
            "targeted_verification", "Verifying repaired records",
            lambda: verify_targeted_output(
                temporary, replacements, source=source, plan=patch_plan,
                write_result=write_result, cancelled=cancelled,
                progress=verify_progress, envelope=envelope,
            ),
            current=0, total=len(replacements), cancellable=True,
        )
        report.targeted_verification = {
            "passed": verification.passed,
            "intended": verification.intended,
            "verified": verification.verified,
            "remaining": verification.remaining,
            "header_valid": verification.header_valid,
            "footer_valid": verification.footer_valid,
            "data_valid": verification.data_valid,
            "endsec_valid": verification.endsec_valid,
            "plausible_size": verification.plausible_size,
            "records_unchanged_except_context": verification.records_unchanged_except_context,
            "wrong_step_ids": verification.wrong_step_ids,
            "messages": verification.messages,
            "duplicate_step_ids": (
                report.file_assessment.prescan_counts.get(
                    "DUPLICATE_STEP_IDS", 0
                )
                if report.file_assessment else "Not assessed"
            ),
            "replacement_references_exist": all(
                item.proposed_context is not None
                and item.proposed_context.step_id > 0
                for item in selected
            ),
            "relationship_records_unchanged": (
                "Proved by exact byte-range change audit"
            ),
        }
        if not verification.passed:
            raise OutputError("Targeted output verification failed: " + "; ".join(
                verification.messages
            ))

        audit_started = time.perf_counter()

        def audit_progress(current: int, total: int) -> None:
            elapsed = max(0.000001, time.perf_counter() - audit_started)
            throughput = current / elapsed
            emit(
                telemetry, "unexpected_change_audit", "Checking for unintended changes",
                bytes_processed=current, bytes_total=total,
                elapsed_seconds=elapsed,
                throughput_bytes_per_second=throughput,
                estimated_remaining_seconds=((total - current) / throughput if throughput else None),
                cancellable=True,
            )

        change_audit = timed(
            "unexpected_change_audit", "Checking for unintended STEP record changes",
            lambda: audit_targeted_changes(
                source, temporary, patch_plan, write_result,
                cancelled=cancelled, progress=audit_progress,
            ), indeterminate=False, cancellable=True,
        )
        report.change_audit = {
            "passed": change_audit.passed,
            "expected_modified_records": change_audit.expected_modified_records,
            "actual_modified_records": change_audit.actual_modified_records,
            "unexpected_modified_records": change_audit.unexpected_modified_records,
            "changed_step_ids": change_audit.changed_step_ids,
            "unexpected_step_ids": change_audit.unexpected_step_ids,
            "messages": change_audit.messages,
            "added_records": 0 if change_audit.passed else "Unknown",
            "deleted_records": 0 if change_audit.passed else "Unknown",
        }
        if not change_audit.passed:
            raise OutputError("Unexpected output changes detected: " + "; ".join(
                change_audit.messages
            ))

        if config.full_validation:
            def full_validate() -> None:
                reopened = open_model(temporary)
                report.validation_after = validate_schema(reopened)
                (report.validation_new, report.validation_resolved,
                 report.validation_unchanged) = classify_issues(
                    report.validation_before, report.validation_after
                )
                new_errors = [
                    issue for issue in report.validation_new
                    if issue.level.casefold() == "error"
                ]
                if new_errors:
                    raise OutputError(
                        f"Full validation found {len(new_errors)} new error(s)"
                    )

            timed(
                "full_validation_after", "Running optional full IFC validation",
                full_validate, indeterminate=True, cancellable=False,
            )
        else:
            report.durations["full_validation_after"] = 0.0
            log_event(
                "full_validation_after", "skipped",
                message="Fast targeted verification selected",
            )

        if cancelled and cancelled():
            raise CancelledError("Repair cancelled before installing the verified output")

        def install_output() -> None:
            nonlocal source_was_replaced
            assert temporary is not None
            os.replace(temporary, output)
            source_was_replaced = output == source

        timed(
            "atomic_replacement", "Installing verified repaired IFC",
            install_output, current=1, total=1, cancellable=False,
        )
        temporary = None
        report.temporary_path = None
        report.output = str(output)
        report.repair_mode = (
            f"{config.repair_mode.title()} Repair - targeted STEP attribute patch"
        )
        report.output_size = output.stat().st_size
        for item in selected:
            item.repaired = True
            item.status = Status.REPAIRED
            item.validation_result = "Targeted output verified"
        repaired_by_type: dict[str, int] = {}
        for item in selected:
            if item.product_class:
                repaired_by_type[item.product_class] = (
                    repaired_by_type.get(item.product_class, 0) + 1
                )
        for product_type, counts in report.element_type_counts.items():
            repaired_count = repaired_by_type.get(product_type, 0)
            counts["successfully_repaired"] = repaired_count
            counts["targeted_issues_remaining"] = max(
                0, counts.get("affected_representations", 0) - repaired_count,
            )
        for classification, counts in report.classification_counts.items():
            repaired_count = sum(
                item.repaired and item.classification.value == classification
                for item in report.diagnoses
            )
            counts["repaired"] = repaired_count
            counts["remaining"] = max(0, counts.get("detected", 0) - repaired_count)
        report.summary_counts["SuccessfullyRepaired"] = len(selected)
        report.summary_counts["TargetedIssuesRemaining"] = (
            len(report.diagnoses) - len(selected)
        )
        report.finished_at = datetime.now(timezone.utc).isoformat()

        report.system_diagnostics.update(system_snapshot(output.parent))
        if config.generate_report:
            report_base = output.with_name(f"{source.stem}_IFCSG_Repair_Report")
            try:
                pdf_path = report_base.with_suffix(".pdf")
                html_path = report_base.with_suffix(".html")
                timed(
                    "generate_pdf_report", "Generating PDF summary",
                    lambda: write_pdf(report, pdf_path), indeterminate=True,
                    cancellable=True,
                )
                report.report_paths["pdf"] = str(pdf_path)
                if cancelled and cancelled():
                    raise CancelledError("Report generation cancelled after PDF completion")
                timed(
                    "generate_html_report", "Generating HTML engineering report",
                    lambda: write_html(report, html_path, cancelled=cancelled), indeterminate=True,
                    cancellable=True,
                )
                report.report_paths["html"] = str(html_path)
            except Exception as exc:
                if isinstance(exc, CancelledError):
                    raise
                report.errors.append(f"Report generation failed: {exc}")
        else:
            report.durations["generate_pdf_report"] = 0.0
            report.durations["generate_html_report"] = 0.0

        report.total_duration_seconds = time.perf_counter() - total_started
        report.finished_at = datetime.now(timezone.utc).isoformat()
        emit(telemetry, "repair_complete", "Repair and verification complete", current=1, total=1)
        _legacy_progress(progress, "Repair complete", 1, 1, 100)
        return report
    except Exception as exc:
        if report is not None:
            report.failed_stage = current_stage
            report.errors.append(f"{type(exc).__name__}: {exc}")
            report.errors.append(traceback.format_exc())
            report.finished_at = datetime.now(timezone.utc).isoformat()
        log_event(
            current_stage, "operation_failed", message=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
            source_unchanged=True,
        )
        try:
            setattr(exc, "repair_context", {
                "input_path": str(source),
                "temporary_output_path": str(temporary) if temporary else "",
                "final_output_path": str(output),
                "source_remains_unchanged": not source_was_replaced,
                "log_path": str(diagnostic_log) if config.debug_logging else "",
            })
        except Exception:
            pass
        raise
    finally:
        cleanup_mark = time.perf_counter()
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)
        cleanup_duration = time.perf_counter() - cleanup_mark
        if report is not None:
            report.durations["cleanup"] = cleanup_duration
            report.total_duration_seconds = time.perf_counter() - total_started
        try:
            log_event(
                "cleanup", "completed", duration=cleanup_duration,
                total_duration_seconds=round(time.perf_counter() - total_started, 6),
            )
        except Exception:
            pass
