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


class RepresentationClassification(str, Enum):
    DIRECT_PRODUCT = "DIRECT_PRODUCT"
    SHAPE_ASPECT_PRODUCT = "SHAPE_ASPECT_PRODUCT"
    SHAPE_ASPECT_REPRESENTATION_MAP = "SHAPE_ASPECT_REPRESENTATION_MAP"
    REPRESENTATION_MAP = "REPRESENTATION_MAP"
    ORPHANED = "ORPHANED"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    AMBIGUOUS = "AMBIGUOUS"


class IfcSgClassification(str, Enum):
    LIKELY = "Likely IFC+SG"
    POSSIBLE = "Possibly IFC+SG"
    NOT_IDENTIFIABLE = "Not identifiable as IFC+SG"
    UNSUPPORTED = "Unsupported"


class ProcessingStrategy(str, Enum):
    FULL_SEMANTIC = "FULL_SEMANTIC"
    HYBRID = "HYBRID"
    STREAMING_FIRST = "STREAMING_FIRST"
    LIMITED_AUDIT = "LIMITED_AUDIT"


class RuleMaturity(str, Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    BETA = "BETA"
    PRODUCTION = "PRODUCTION"


@dataclass(slots=True)
class AuditFinding:
    rule_id: str
    category: str
    title: str
    entity_step_id: int | None
    entity_type: str | None
    global_id: str | None = None
    name: str | None = None
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    confidence: str = "REPORT_ONLY"
    action: str = "Report only"
    schema_validity: str = "Not assessed"
    rendering_impact: str = "Not assessed"
    downstream_impact: str = "Not assessed"
    submission_risk: str = "Not assessed"
    repair_priority: str = "Not assessed"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IfcSgAssessment:
    classification: IfcSgClassification
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    likely_exporter: str = "Unknown"
    exporter_evidence: list[str] = field(default_factory=list)
    score: int = 0


@dataclass(slots=True)
class FileAssessment:
    original_name: str
    working_name: str
    input_kind: str
    schema: str | None
    size_bytes: int
    size_category: str
    strategy: ProcessingStrategy
    available_memory_bytes: int | None = None
    available_disk_bytes: int | None = None
    estimated_output_bytes: int | None = None
    ifc_sg: IfcSgAssessment | None = None
    prescan_counts: dict[str, int] = field(default_factory=dict)


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
    classification: RepresentationClassification = (
        RepresentationClassification.DIRECT_PRODUCT
    )
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    usage_count: int = 0
    ultimate_product_count: int = 0
    ultimate_product_classes: dict[str, int] = field(default_factory=dict)
    schema_status: str = "Invalid - ContextOfItems is missing"
    rendering_risk: str = "Unknown"
    downstream_processing_risk: str = "Unknown"
    repair_priority: str = "Unknown"
    proposed_action: str = "Report only"
    repair_signature: str = ""
    safety_level: str = "Report Only"
    viewer_test_status: str = "Not Tested"
    production_enabled: bool = False
    repair_decision_reason: str = ""

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
    element_type_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    classification_counts: dict[str, dict[str, int]] = field(default_factory=dict)
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
    file_assessment: FileAssessment | None = None
    audit_findings: list[AuditFinding] = field(default_factory=list)
    selected_rules: list[str] = field(default_factory=list)
    skipped_rules: dict[str, str] = field(default_factory=dict)
    rule_metadata: list[dict[str, Any]] = field(default_factory=list)
    repair_signature_statuses: list[dict[str, Any]] = field(default_factory=list)
    generated_outputs: list[dict[str, Any]] = field(default_factory=list)
    disclaimer: str = (
        "This application performs targeted repairs for known IFC+SG export issues. "
        "It is not a complete IFC validator or CORENET X compliance checker. "
        "A repaired IFC should still undergo the normal submission validation process."
    )

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
