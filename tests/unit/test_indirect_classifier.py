from __future__ import annotations

from collections import Counter

from ifc_context_repair.indirect import (
    RepresentationGraphIndex,
    _classification,
    _compatible,
    _resolve,
    is_repairable_in_mode,
)
from ifc_context_repair.models import (
    ConfidenceLevel,
    ContextInfo,
    Diagnosis,
    RepresentationClassification,
    Status,
)


class Entity:
    def __init__(self, step_id: int, type_name: str, **attributes: object) -> None:
        self._step_id = step_id
        self._type_name = type_name
        for name, value in attributes.items():
            setattr(self, name, value)

    def id(self) -> int:
        return self._step_id

    def is_a(self, type_name: str | None = None):
        if type_name is None:
            return self._type_name
        return self._type_name == type_name


def context(step_id: int, identifier: str = "Body") -> ContextInfo:
    return ContextInfo(
        step_id=step_id,
        entity_type="IfcGeometricRepresentationSubContext",
        identifier=identifier,
        context_type="Model",
        target_view="PLAN_VIEW" if identifier == "FootPrint" else "MODEL_VIEW",
        parent_step_id=1,
        dimension=3 if identifier == "Body" else 2,
        connected_to_project=True,
    )


def diagnosis(
    classification: RepresentationClassification,
    step_id: int = 100,
) -> Diagnosis:
    return Diagnosis(
        representation_step_id=step_id,
        representation_identifier="Body",
        representation_type="SweptSolid",
        item_count=1,
        item_classes=["IfcExtrudedAreaSolid"],
        current_context_step_id=None,
        classification=classification,
    )


def base_index() -> tuple[RepresentationGraphIndex, Entity, Entity]:
    ctx_10 = Entity(10, "IfcGeometricRepresentationSubContext")
    ctx_11 = Entity(11, "IfcGeometricRepresentationSubContext")
    target = Entity(
        100, "IfcShapeRepresentation",
        RepresentationIdentifier="Body", RepresentationType="SweptSolid",
        ContextOfItems=None, Items=(),
    )
    index = RepresentationGraphIndex(
        contexts={10: ctx_10, 11: ctx_11},
        context_info={10: context(10), 11: context(11)},
        project_context_ids={10, 11},
        shape_representations={100: target},
    )
    return index, target, ctx_10


def test_context_compatibility_rules() -> None:
    assert _compatible(context(10), ("body", "sweptsolid"))
    assert _compatible(context(10), ("body", "tessellation"))
    assert _compatible(context(20, "FootPrint"), ("footprint", "curve2d"))
    assert not _compatible(context(10), ("footprint", "curve2d"))


def test_shape_aspect_product_uses_unique_sibling_context() -> None:
    index, target, ctx_10 = base_index()
    sibling = Entity(
        101, "IfcShapeRepresentation",
        RepresentationIdentifier="Body", RepresentationType="SweptSolid",
        ContextOfItems=ctx_10, Items=(),
    )
    index.shape_representations[101] = sibling
    index.representation_to_aspects[100] = [300]
    index.aspect_parent_pds[300] = [200]
    index.pds_to_representations[200] = [101]
    item = diagnosis(RepresentationClassification.SHAPE_ASPECT_PRODUCT)

    _resolve(target, item, index)

    assert item.status is Status.SAFE
    assert item.confidence_level is ConfidenceLevel.HIGH
    assert item.proposed_context and item.proposed_context.step_id == 10


def test_shape_aspect_conflicting_siblings_are_ambiguous() -> None:
    index, target, ctx_10 = base_index()
    sibling_a = Entity(
        101, "IfcShapeRepresentation",
        RepresentationIdentifier="Body", RepresentationType="SweptSolid",
        ContextOfItems=ctx_10, Items=(),
    )
    sibling_b = Entity(
        102, "IfcShapeRepresentation",
        RepresentationIdentifier="Body", RepresentationType="SweptSolid",
        ContextOfItems=index.contexts[11], Items=(),
    )
    index.shape_representations.update({101: sibling_a, 102: sibling_b})
    index.representation_to_aspects[100] = [300]
    index.aspect_parent_pds[300] = [200]
    index.pds_to_representations[200] = [101, 102]
    item = diagnosis(RepresentationClassification.SHAPE_ASPECT_PRODUCT)

    _resolve(target, item, index)

    assert item.status is Status.AMBIGUOUS
    assert item.proposed_context is None


def test_representation_map_many_usages_must_agree() -> None:
    index, target, ctx_10 = base_index()
    outer_a = Entity(401, "IfcShapeRepresentation", ContextOfItems=ctx_10)
    outer_b = Entity(402, "IfcShapeRepresentation", ContextOfItems=ctx_10)
    index.shape_representations.update({401: outer_a, 402: outer_b})
    index.representation_to_maps[100] = [500]
    index.map_to_usages[500] = [601, 602]
    index.item_to_representations.update({601: [401], 602: [402]})
    item = diagnosis(RepresentationClassification.REPRESENTATION_MAP)

    _resolve(target, item, index)

    assert item.status is Status.SAFE
    assert item.proposed_context and item.proposed_context.step_id == 10


def test_representation_map_conflicting_usages_are_never_repaired() -> None:
    index, target, ctx_10 = base_index()
    outer_a = Entity(401, "IfcShapeRepresentation", ContextOfItems=ctx_10)
    outer_b = Entity(
        402, "IfcShapeRepresentation", ContextOfItems=index.contexts[11]
    )
    index.shape_representations.update({401: outer_a, 402: outer_b})
    index.representation_to_maps[100] = [500]
    index.map_to_usages[500] = [601, 602]
    index.item_to_representations.update({601: [401], 602: [402]})
    item = diagnosis(RepresentationClassification.REPRESENTATION_MAP)

    _resolve(target, item, index)

    assert item.status is Status.AMBIGUOUS
    assert item.proposed_context is None


def test_unused_representation_map_is_report_only() -> None:
    index, target, _ctx_10 = base_index()
    index.representation_to_maps[100] = [500]
    index.semantic_contexts[("body", "sweptsolid")] = Counter({10: 10})
    item = diagnosis(RepresentationClassification.REPRESENTATION_MAP)

    _resolve(target, item, index)

    assert item.confidence_level is ConfidenceLevel.LOW
    assert item.proposed_context is None


def test_type_owned_footprint_without_occurrences_is_high_confidence() -> None:
    root = Entity(24, "IfcGeometricRepresentationContext")
    body_context = Entity(26, "IfcGeometricRepresentationSubContext")
    footprint_context = Entity(28, "IfcGeometricRepresentationSubContext")
    target = Entity(
        100, "IfcShapeRepresentation",
        RepresentationIdentifier="FootPrint", RepresentationType="Curve2D",
        ContextOfItems=None, Items=(),
    )
    body = Entity(
        101, "IfcShapeRepresentation",
        RepresentationIdentifier="Body", RepresentationType="SweptSolid",
        ContextOfItems=body_context, Items=(),
    )
    target_map = Entity(500, "IfcRepresentationMap", MappedRepresentation=target)
    body_map = Entity(501, "IfcRepresentationMap", MappedRepresentation=body)
    owner = Entity(
        600, "IfcPlateType", RepresentationMaps=(body_map, target_map)
    )
    footprint_info = ContextInfo(
        28, "IfcGeometricRepresentationSubContext", "FootPrint", "Model",
        target_view="MODEL_VIEW", parent_step_id=24, dimension=3,
        connected_to_project=True,
    )
    body_info = ContextInfo(
        26, "IfcGeometricRepresentationSubContext", "Body", "Model",
        target_view="MODEL_VIEW", parent_step_id=24, dimension=3,
        connected_to_project=True,
    )
    index = RepresentationGraphIndex(
        contexts={24: root, 26: body_context, 28: footprint_context},
        context_info={26: body_info, 28: footprint_info},
        project_context_ids={24, 26, 28},
        shape_representations={100: target, 101: body},
        representation_to_maps={100: [500]},
        maps={500: target_map, 501: body_map},
        type_products={600: owner},
        map_to_type_products={500: [600], 501: [600]},
        type_product_to_maps={600: [501, 500]},
    )
    index.semantic_contexts[("footprint", "curve2d")] = Counter({28: 89})
    item = Diagnosis(
        representation_step_id=100,
        representation_identifier="FootPrint",
        representation_type="Curve2D",
        item_count=1,
        item_classes=["IfcPolyline"],
        current_context_step_id=None,
        classification=RepresentationClassification.REPRESENTATION_MAP,
    )

    _resolve(target, item, index)

    assert item.status is Status.SAFE
    assert item.confidence_level is ConfidenceLevel.HIGH
    assert item.proposed_context and item.proposed_context.step_id == 28
    assert is_repairable_in_mode(item, "advanced")


def test_unsupported_and_orphaned_classifications() -> None:
    index, _target, _ctx_10 = base_index()
    classification, _ = _classification(
        100, ("axis", "curve3d"), index
    )
    assert classification is RepresentationClassification.UNSUPPORTED
    classification, _ = _classification(
        100, ("body", "sweptsolid"), index
    )
    assert classification is RepresentationClassification.ORPHANED


def test_repair_modes_are_strict() -> None:
    direct = diagnosis(RepresentationClassification.DIRECT_PRODUCT)
    direct.status = Status.SAFE
    direct.confidence_level = ConfidenceLevel.HIGH
    direct.proposed_context = context(10)
    indirect = diagnosis(RepresentationClassification.REPRESENTATION_MAP)
    indirect.status = Status.SAFE
    indirect.confidence_level = ConfidenceLevel.HIGH
    indirect.proposed_context = context(10)

    assert is_repairable_in_mode(direct, "safe")
    assert not is_repairable_in_mode(indirect, "safe")
    assert is_repairable_in_mode(indirect, "extended")
    assert not is_repairable_in_mode(direct, "audit")
