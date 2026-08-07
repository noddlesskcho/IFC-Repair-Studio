from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..detector import diagnose_model
from ..indirect import classify_missing_contexts, is_repairable_in_mode
from ..models import (
    ConfidenceLevel,
    Diagnosis,
    RepresentationClassification,
    Status,
)
from ..repair_safety import apply_signature_policy


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
    type_counts: dict[str, dict[str, int]]
    classification_counts: dict[str, dict[str, int]]


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
        repair_mode: str = "safe",
    ) -> RuleScanResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ElementPolicy:
    product_type: str
    rule_id: str
    allowed_signatures: frozenset[tuple[str, str]]


ELEMENT_POLICIES = (
    ElementPolicy(
        "IfcSlab", "SLAB_MISSING_SHAPE_CONTEXT_V1",
        frozenset({("body", "sweptsolid"), ("footprint", "curve2d")}),
    ),
    ElementPolicy(
        "IfcWall", "WALL_MISSING_SHAPE_CONTEXT_V1",
        frozenset({
            ("axis", "curve3d"), ("body", "sweptsolid"),
            ("body", "tessellation"),
        }),
    ),
    ElementPolicy(
        "IfcOpeningElement", "OPENING_MISSING_SHAPE_CONTEXT_V1",
        frozenset({("body", "sweptsolid"), ("body", "tessellation")}),
    ),
    ElementPolicy(
        "IfcRailing", "RAILING_MISSING_SHAPE_CONTEXT_V1",
        frozenset({
            ("body", "mappedrepresentation"), ("body", "sweptsolid"),
            ("body", "tessellation"),
        }),
    ),
    ElementPolicy(
        "IfcCovering", "COVERING_MISSING_SHAPE_CONTEXT_V1",
        frozenset({
            ("body", "sweptsolid"), ("body", "tessellation"),
            ("footprint", "curve2d"),
        }),
    ),
)


class ProductMissingShapeContextRule(RepairRule):
    rule_id = "DIRECT_PRODUCT_MISSING_CONTEXT_V1"
    version = "1.0"
    display_name = "Direct Product Geometry Reference Repair"
    description = (
        "Repairs supported missing geometry references on directly owned "
        "IfcProduct shape representations."
    )
    supported_schemas = ("IFC4",)
    supported_product_types = ("IfcProduct",)
    supported_signatures = frozenset({
        ("body", "sweptsolid"),
        ("body", "tessellation"),
        ("footprint", "curve2d"),
    })
    allowed_signatures = {"*": supported_signatures}

    def detect(
        self, model: Any, *, timings: dict[str, float] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        repair_mode: str = "safe",
    ) -> RuleScanResult:
        diagnoses, index = diagnose_model(
            model, product_types=self.supported_product_types,
            allowed_signatures=self.allowed_signatures,
            timings=timings, progress=progress, cancelled=cancelled,
        )
        for item in diagnoses:
            item.classification = RepresentationClassification.DIRECT_PRODUCT
            signature = (
                str(item.representation_identifier or "").casefold(),
                str(item.representation_type or "").casefold(),
            )
            item.rule_id = {
                ("body", "sweptsolid"):
                    "DIRECT_PRODUCT_BODY_SWEPTSOLID_MISSING_CONTEXT_V1",
                ("body", "tessellation"):
                    "DIRECT_PRODUCT_BODY_TESSELLATION_MISSING_CONTEXT_V1",
                ("footprint", "curve2d"):
                    "DIRECT_PRODUCT_FOOTPRINT_CURVE2D_MISSING_CONTEXT_V1",
            }.get(signature, self.rule_id)
            item.repair_signature = (
                f"DirectProduct/{item.representation_identifier or '-'}"
                f"/{item.representation_type or '-'}"
            )
            repairable = (
                item.status is Status.SAFE and item.proposed_context is not None
            )
            item.confidence_level = (
                ConfidenceLevel.HIGH if repairable else ConfidenceLevel.LOW
            )
            item.production_enabled = repairable
            item.safety_level = "Production-Safe" if repairable else "Report Only"
            item.viewer_test_status = "Version 1 supported scope"
            item.proposed_action = (
                "Repair" if repairable else "Unable to determine safely"
            )
            item.repair_decision_reason = (
                "Direct ownership, supported signature and one unique compatible "
                "project context were proven."
                if repairable else
                "The Version 1 direct-product evidence requirements were not all met."
            )
        targets = [
            RepairTarget(
                product_step_id=item.product_step_id,
                product_global_id=item.product_global_id,
                product_type=item.product_class or "IfcProduct",
                product_name=item.product_name,
                representation_step_id=item.representation_step_id,
                representation_identifier=item.representation_identifier or "",
                representation_type=item.representation_type or "",
                original_context_step_id=item.current_context_step_id,
                proposed_context_step_id=(
                    item.proposed_context.step_id if item.proposed_context else None
                ),
                rule_id=item.rule_id or self.rule_id,
                confidence=item.confidence,
                automatically_repairable=(
                    item.status is Status.SAFE and item.proposed_context is not None
                ),
            )
            for item in diagnoses
        ]
        affected = {item.product_step_id or item.owner_step_id for item in diagnoses}
        type_counts: dict[str, dict[str, int]] = {}
        for product_type in sorted(index.products_by_scope):
            scoped = [
                item for item in diagnoses
                if index.product_scope.get(item.product_step_id or -1) == product_type
            ]
            # Ordinary reports are issue-focused. Product classes that were
            # scanned but had no supported finding add noise without improving
            # the element breakdown.
            if not scoped:
                continue
            type_counts[product_type] = {
                "elements_scanned": int(index.products_by_scope[product_type]),
                "elements_affected": len({
                    item.product_step_id or item.owner_step_id for item in scoped
                }),
                "representations_scanned": int(
                    index.representations_by_scope[product_type]
                ),
                "affected_representations": len(scoped),
                "automatically_repairable": sum(
                    item.status is Status.SAFE and item.proposed_context is not None
                    for item in scoped
                ),
                "not_automatically_repairable": sum(
                    item.status is not Status.SAFE or item.proposed_context is None
                    for item in scoped
                ),
                "successfully_repaired": 0,
                "targeted_issues_remaining": len(scoped),
            }
        return RuleScanResult(
            rule_id=self.rule_id,
            rule_version=self.version,
            diagnoses=diagnoses,
            targets=targets,
            elements_scanned=index.total_products,
            elements_affected=len(affected),
            representations_scanned=index.total_shape_representations,
            type_counts=type_counts,
            classification_counts={},
        )


class SlabMissingShapeContextRule(ProductMissingShapeContextRule):
    """Compatibility rule retained for callers that explicitly require slab-only v1."""

    rule_id = "SLAB_MISSING_SHAPE_CONTEXT_V1"
    version = "1.0"
    display_name = "Slab - Missing Shape Representation Context"
    supported_product_types = ("IfcSlab",)
    allowed_signatures = {
        "IfcSlab": frozenset({
            ("body", "sweptsolid"), ("footprint", "curve2d")
        })
    }


class EnhancedMissingShapeContextRule(RepairRule):
    rule_id = "MISSING_SHAPE_CONTEXT_CLASSIFIER_V1"
    version = "1.0"
    display_name = "Safe and Extended Representation Context Repair"
    description = (
        "Classifies every missing IfcShapeRepresentation context and repairs only "
        "uniquely proven direct or indirect cases allowed by the selected mode."
    )
    supported_schemas = ("IFC2X3", "IFC4", "IFC4X3")
    supported_product_types = ("IfcProduct",)

    def detect(
        self, model: Any, *, timings: dict[str, float] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        repair_mode: str = "safe",
    ) -> RuleScanResult:
        diagnoses, index = classify_missing_contexts(
            model, timings=timings, progress=progress, cancelled=cancelled,
        )
        targets = [
            RepairTarget(
                product_step_id=item.product_step_id,
                product_global_id=item.product_global_id,
                product_type=item.product_class or "Indirect representation",
                product_name=item.product_name,
                representation_step_id=item.representation_step_id,
                representation_identifier=item.representation_identifier or "",
                representation_type=item.representation_type or "",
                original_context_step_id=item.current_context_step_id,
                proposed_context_step_id=(
                    item.proposed_context.step_id if item.proposed_context else None
                ),
                rule_id=item.rule_id or self.rule_id,
                confidence=item.confidence,
                automatically_repairable=is_repairable_in_mode(item, repair_mode),
            )
            for item in diagnoses
        ]
        product_ids = {
            product_id
            for item in diagnoses
            for product_id in index.products_for_representation(
                item.representation_step_id
            )
        }
        type_counts: dict[str, dict[str, int]] = {}
        for product_type in sorted({
            entity.is_a() for entity in index.products.values()
        }):
            product_steps = {
                product_id for product_id, product in index.products.items()
                if product.is_a() == product_type
            }
            scoped = [
                item for item in diagnoses
                if product_steps.intersection(
                    index.products_for_representation(item.representation_step_id)
                )
            ]
            if not scoped:
                continue
            type_counts[product_type] = {
                "elements_scanned": len(product_steps),
                "elements_affected": len(product_steps.intersection(product_ids)),
                "representations_scanned": 0,
                "affected_representations": len(scoped),
                "automatically_repairable": sum(
                    is_repairable_in_mode(item, repair_mode) for item in scoped
                ),
                "not_automatically_repairable": sum(
                    not is_repairable_in_mode(item, repair_mode) for item in scoped
                ),
                "successfully_repaired": 0,
                "targeted_issues_remaining": len(scoped),
            }
        classification_counts: dict[str, dict[str, int]] = {}
        for classification in RepresentationClassification:
            scoped = [
                item for item in diagnoses if item.classification is classification
            ]
            classification_counts[classification.value] = {
                "detected": len(scoped),
                "high_confidence": sum(
                    item.status is Status.SAFE and item.proposed_context is not None
                    for item in scoped
                ),
                "auto_repair": sum(
                    is_repairable_in_mode(item, repair_mode) for item in scoped
                ),
                "reported_only": sum(
                    not is_repairable_in_mode(item, repair_mode) for item in scoped
                ),
                "production_safe": sum(item.production_enabled for item in scoped),
                "experimental": sum(
                    item.safety_level == "Experimental" for item in scoped
                ),
                "repaired": 0,
                "remaining": len(scoped),
            }
        return RuleScanResult(
            rule_id=self.rule_id,
            rule_version=self.version,
            diagnoses=diagnoses,
            targets=targets,
            elements_scanned=len(index.products),
            elements_affected=len(product_ids),
            representations_scanned=len(index.shape_representations),
            type_counts=type_counts,
            classification_counts=classification_counts,
        )


ACTIVE_RULE = ProductMissingShapeContextRule()
