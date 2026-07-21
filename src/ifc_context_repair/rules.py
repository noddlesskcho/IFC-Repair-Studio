from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .detector import diagnose_model
from .models import Diagnosis, Status


@dataclass(frozen=True, slots=True)
class RepairTarget:
    product_step_id: int | None
    product_global_id: str | None
    product_type: str
    product_name: str | None
    representation_step_id: int
    representation_identifier: str
    representation_type: str
    original_context_step_id: int | None
    proposed_context_step_id: int | None
    rule_id: str
    confidence: float
    automatically_repairable: bool


@dataclass(slots=True)
class RuleScanResult:
    rule_id: str
    rule_version: str
    diagnoses: list[Diagnosis]
    targets: list[RepairTarget]
    elements_scanned: int
    elements_affected: int
    representations_scanned: int


class RepairRule(ABC):
    rule_id: str
    version: str
    display_name: str
    description: str
    supported_schemas: tuple[str, ...]
    supported_product_types: tuple[str, ...]

    @abstractmethod
    def detect(
        self, model: Any, *, timings: dict[str, float] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> RuleScanResult:
        raise NotImplementedError


class SlabMissingShapeContextRule(RepairRule):
    rule_id = "SLAB_MISSING_SHAPE_CONTEXT_V1"
    version = "1.0"
    display_name = "Slab - Missing Shape Representation Context"
    description = (
        "Repairs missing ContextOfItems on directly owned IfcSlab Body/SweptSolid "
        "and FootPrint/Curve2D representations."
    )
    supported_schemas = ("IFC2X3", "IFC4", "IFC4X3")
    supported_product_types = ("IfcSlab",)
    allowed_signatures = {
        ("body", "sweptsolid"),
        ("footprint", "curve2d"),
    }

    def detect(
        self, model: Any, *, timings: dict[str, float] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> RuleScanResult:
        diagnoses, index = diagnose_model(
            model, timings=timings, progress=progress, cancelled=cancelled
        )
        scoped = [
            item for item in diagnoses
            if (
                (item.representation_identifier or "").casefold(),
                (item.representation_type or "").casefold(),
            ) in self.allowed_signatures
        ]
        for item in scoped:
            item.rule_id = self.rule_id
        targets = [
            RepairTarget(
                product_step_id=item.product_step_id,
                product_global_id=item.product_global_id,
                product_type=item.product_class or "IfcSlab",
                product_name=item.product_name,
                representation_step_id=item.representation_step_id,
                representation_identifier=item.representation_identifier or "",
                representation_type=item.representation_type or "",
                original_context_step_id=item.current_context_step_id,
                proposed_context_step_id=(
                    item.proposed_context.step_id if item.proposed_context else None
                ),
                rule_id=self.rule_id,
                confidence=item.confidence,
                automatically_repairable=(
                    item.status is Status.SAFE and item.proposed_context is not None
                ),
            )
            for item in scoped
        ]
        affected = {
            item.product_global_id or f"owner-{item.owner_step_id}" for item in scoped
        }
        return RuleScanResult(
            rule_id=self.rule_id,
            rule_version=self.version,
            diagnoses=scoped,
            targets=targets,
            elements_scanned=index.total_products,
            elements_affected=len(affected),
            representations_scanned=index.total_shape_representations,
        )


ACTIVE_RULE = SlabMissingShapeContextRule()
