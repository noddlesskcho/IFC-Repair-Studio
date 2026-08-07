from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ...models import AuditFinding, Diagnosis
from ...feature_flags import RepairFeatureFlags
from ...prescan import StepPrescanProfile


@dataclass(slots=True)
class IfcSgRuleContext:
    model: Any
    schema: str
    profile: StepPrescanProfile
    diagnoses: list[Diagnosis] = field(default_factory=list)
    shared: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RepairProposal:
    rule_id: str
    target_step_id: int
    target_entity: str
    attribute: str
    current_value: str
    proposed_value: str
    evidence: list[str]
    confidence: str
    expected_record_difference: str


@dataclass(slots=True)
class RuleVerificationResult:
    passed: bool
    messages: list[str] = field(default_factory=list)


class IfcSgRule(ABC):
    rule_id: str
    title: str
    purpose: str
    maturity: str
    repair_mode: str
    supported_schemas: frozenset[str]
    supported_exporter_patterns: tuple[str, ...]
    supported_signatures: tuple[str, ...]
    repair_capability: str
    confidence_requirement: str
    known_limitations: tuple[str, ...]
    category: str
    feature_flag: str | None = None

    def is_enabled(self, feature_flags: RepairFeatureFlags) -> bool:
        """Return false before any rule-specific precomputation can occur."""
        return self.feature_flag is None or bool(
            getattr(feature_flags, self.feature_flag)
        )

    def is_applicable(self, context: IfcSgRuleContext) -> bool:
        return context.schema.upper() in self.supported_schemas

    @abstractmethod
    def detect(
        self, context: IfcSgRuleContext
    ) -> list[Diagnosis | AuditFinding]:
        raise NotImplementedError

    def classify(
        self, issue: Diagnosis | AuditFinding, context: IfcSgRuleContext
    ) -> str:
        return getattr(issue, "confidence_level", None) or getattr(
            issue, "confidence", "REPORT_ONLY"
        )

    def propose_repair(
        self, issue: Diagnosis | AuditFinding, context: IfcSgRuleContext
    ) -> RepairProposal | None:
        return None

    def verify(
        self, proposal: RepairProposal, before: bytes, after: bytes
    ) -> RuleVerificationResult:
        return RuleVerificationResult(before != after)

    def metadata(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "purpose": self.purpose,
            "workflow": "IFC+SG / CORENET X",
            "maturity": self.maturity,
            "repair_mode": self.repair_mode,
            "supported_schemas": sorted(self.supported_schemas),
            "supported_exporter_patterns": list(self.supported_exporter_patterns),
            "supported_signatures": list(self.supported_signatures),
            "repair_capability": self.repair_capability,
            "confidence_requirement": self.confidence_requirement,
            "known_limitations": list(self.known_limitations),
            "category": self.category,
            "feature_flag": self.feature_flag,
        }
