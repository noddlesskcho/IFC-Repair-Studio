from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Status(str, Enum):
    SAFE = "Safe to repair"
    WARNING = "Repairable with warning"
    AMBIGUOUS = "Ambiguous"
    NOT_REPAIRABLE = "Not repairable"
    VALID = "Already valid"
    REPAIRED = "Repaired"


@dataclass(slots=True)
class PrescanCandidate:
    step_id: int | None
    byte_offset: int
    line_number: int
    record_preview: str


@dataclass(slots=True)
class ContextInfo:
    step_id: int
    entity_type: str
    identifier: str | None
    context_type: str | None
    target_view: str | None = None
    parent_step_id: int | None = None
    dimension: int | None = None
    connected_to_project: bool = False


@dataclass(slots=True)
class Diagnosis:
    representation_step_id: int
    representation_identifier: str | None
    representation_type: str | None
    item_count: int
    item_classes: list[str]
    current_context_step_id: int | None
    product_class: str | None = None
    product_step_id: int | None = None
    product_global_id: str | None = None
    product_name: str | None = None
    product_tag: str | None = None
    owner_step_id: int | None = None
    rule_id: str | None = None
    proposed_context: ContextInfo | None = None
    candidates: list[ContextInfo] = field(default_factory=list)
    status: Status = Status.NOT_REPAIRABLE
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    decision_trace: list[dict[str, Any]] = field(default_factory=list)
    validation_result: str = "Not run"
    repaired: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


@dataclass(slots=True)
class ValidationIssue:
    level: str
    message: str
    entity_step_id: int | None = None
    attribute: str | None = None


@dataclass(slots=True)
class FileSnapshot:
    schema: str | None
    counts: dict[str, int]
    global_ids: dict[str, list[str]]
    representation_items: int
    target_assignments: dict[str, int | None]
    size: int
    sha256: str


@dataclass(slots=True)
class RunReport:
    source: str
    output: str | None = None
    schema: str | None = None
    started_at: str = ""
    finished_at: str = ""
    durations: dict[str, float] = field(default_factory=dict)
    summary_counts: dict[str, int] = field(default_factory=dict)
    active_rule_id: str = ""
    active_rule_version: str = ""
    input_size: int = 0
    output_size: int = 0
    targeted_verification: dict[str, Any] = field(default_factory=dict)
    change_audit: dict[str, Any] = field(default_factory=dict)
    system_diagnostics: dict[str, Any] = field(default_factory=dict)
    full_validation_performed: bool = False
    log_path: str | None = None
    report_paths: dict[str, str] = field(default_factory=dict)
    temporary_path: str | None = None
    failed_stage: str | None = None
    stage_events: list[dict[str, Any]] = field(default_factory=list)
    prescan_candidates: list[PrescanCandidate] = field(default_factory=list)
    diagnoses: list[Diagnosis] = field(default_factory=list)
    validation_before: list[ValidationIssue] = field(default_factory=list)
    validation_after: list[ValidationIssue] = field(default_factory=list)
    validation_new: list[ValidationIssue] = field(default_factory=list)
    validation_resolved: list[ValidationIssue] = field(default_factory=list)
    validation_unchanged: list[ValidationIssue] = field(default_factory=list)
    snapshot_before: FileSnapshot | None = None
    snapshot_after: FileSnapshot | None = None
    repair_mode: str | None = None
    backup: str | None = None
    exporter_header: dict[str, str] = field(default_factory=dict)
    geometry_results: list[dict[str, Any]] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    total_duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        def convert(value: Any) -> Any:
            if hasattr(value, "__dataclass_fields__"):
                return {k: convert(v) for k, v in asdict(value).items()}
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, list):
                return [convert(v) for v in value]
            if isinstance(value, dict):
                return {str(k): convert(v) for k, v in value.items()}
            return value

        return convert(asdict(self))
