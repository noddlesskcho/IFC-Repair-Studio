from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .context_index import attr, entity_id, entity_type
from .errors import CancelledError
from .models import (
    ConfidenceLevel,
    ContextInfo,
    Diagnosis,
    RepresentationClassification,
    Status,
)


Progress = Callable[[str, int, int], None]

SUPPORTED_SIGNATURES = frozenset({
    ("body", "sweptsolid"),
    ("body", "tessellation"),
    ("footprint", "curve2d"),
})

RULE_BY_CLASSIFICATION = {
    RepresentationClassification.DIRECT_PRODUCT:
        "DIRECT_PRODUCT_MISSING_CONTEXT_V2",
    RepresentationClassification.SHAPE_ASPECT_PRODUCT:
        "SHAPE_ASPECT_PRODUCT_MISSING_CONTEXT_V1",
    RepresentationClassification.REPRESENTATION_MAP:
        "REPRESENTATION_MAP_MISSING_CONTEXT_V1",
    RepresentationClassification.SHAPE_ASPECT_REPRESENTATION_MAP:
        "SHAPE_ASPECT_MAP_MISSING_CONTEXT_V1",
}


def _normal(value: object) -> str:
    return str(value or "").strip().casefold()


def _entities(values: Iterable[Any]) -> dict[int, Any]:
    return {
        entity_id(value): value
        for value in values
        if entity_id(value)
    }


@dataclass(slots=True)
class RepresentationGraphIndex:
    contexts: dict[int, Any] = field(default_factory=dict)
    context_info: dict[int, ContextInfo] = field(default_factory=dict)
    project_context_ids: set[int] = field(default_factory=set)
    semantic_contexts: dict[tuple[str, str], Counter[int]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    shape_representations: dict[int, Any] = field(default_factory=dict)
    products: dict[int, Any] = field(default_factory=dict)
    product_to_pds: dict[int, int] = field(default_factory=dict)
    pds_to_products: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    representation_to_pds: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    pds_to_representations: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    representation_to_aspects: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    aspects: dict[int, Any] = field(default_factory=dict)
    aspect_parent_pds: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    aspect_parent_maps: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    representation_to_maps: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    maps: dict[int, Any] = field(default_factory=dict)
    map_to_usages: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    type_products: dict[int, Any] = field(default_factory=dict)
    map_to_type_products: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    type_product_to_maps: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    type_to_occurrences: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    mapped_items: dict[int, Any] = field(default_factory=dict)
    hosted_opening_ids: set[int] = field(default_factory=set)
    item_to_representations: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _map_products_cache: dict[int, set[int]] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        model: Any,
        *,
        progress: Progress | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> "RepresentationGraphIndex":
        index = cls()

        projects = list(model.by_type("IfcProject"))
        root_context_ids: set[int] = set()
        for project in projects:
            root_context_ids.update(
                entity_id(context)
                for context in (attr(project, "RepresentationContexts", ()) or ())
                if entity_id(context)
            )

        contexts = list(model.by_type("IfcGeometricRepresentationContext"))
        known_contexts = {entity_id(context) for context in contexts}
        for context in model.by_type("IfcGeometricRepresentationSubContext"):
            if entity_id(context) not in known_contexts:
                contexts.append(context)
        for context in contexts:
            cid = entity_id(context)
            if not cid:
                continue
            parent = attr(context, "ParentContext")
            parent_id = entity_id(parent)
            connected = cid in root_context_ids or parent_id in root_context_ids
            dimension = attr(context, "CoordinateSpaceDimension")
            if dimension is None and parent is not None:
                dimension = attr(parent, "CoordinateSpaceDimension")
            index.contexts[cid] = context
            index.context_info[cid] = ContextInfo(
                step_id=cid,
                entity_type=entity_type(context) or "Unknown",
                identifier=attr(context, "ContextIdentifier"),
                context_type=(
                    attr(context, "ContextType")
                    or attr(parent, "ContextType")
                ),
                target_view=(
                    str(attr(context, "TargetView"))
                    if attr(context, "TargetView") else None
                ),
                parent_step_id=parent_id,
                dimension=dimension,
                connected_to_project=connected,
            )
            if connected:
                index.project_context_ids.add(cid)
        if progress:
            progress("indirect_context_index", len(contexts), len(contexts))

        index.shape_representations = _entities(
            model.by_type("IfcShapeRepresentation")
        )
        index.products = _entities(model.by_type("IfcProduct"))
        product_values = list(index.products.values())
        for position, product in enumerate(product_values, 1):
            if cancelled and cancelled():
                raise CancelledError("Scan cancelled while indexing product ownership")
            pds = attr(product, "Representation")
            pds_id = entity_id(pds)
            product_id = entity_id(product)
            if not pds_id or not product_id:
                continue
            index.product_to_pds[product_id] = pds_id
            index.pds_to_products[pds_id].append(product_id)
            for representation in attr(pds, "Representations", ()) or ():
                rid = entity_id(representation)
                if rid:
                    index.representation_to_pds[rid].append(pds_id)
                    index.pds_to_representations[pds_id].append(rid)
            for aspect in attr(pds, "HasShapeAspects", ()) or ():
                aspect_id = entity_id(aspect)
                if aspect_id and pds_id not in index.aspect_parent_pds[aspect_id]:
                    index.aspect_parent_pds[aspect_id].append(pds_id)
            if progress and (
                position % 250 == 0 or position == len(product_values)
            ):
                progress("indirect_product_ownership", position, len(product_values))

        index.aspects = _entities(model.by_type("IfcShapeAspect"))
        aspect_values = list(index.aspects.values())
        for position, aspect in enumerate(aspect_values, 1):
            if cancelled and cancelled():
                raise CancelledError("Scan cancelled while indexing shape aspects")
            aid = entity_id(aspect)
            for representation in attr(aspect, "ShapeRepresentations", ()) or ():
                rid = entity_id(representation)
                if rid and aid:
                    index.representation_to_aspects[rid].append(aid)
            parent = attr(aspect, "PartOfProductDefinitionShape")
            parent_id = entity_id(parent)
            if aid and parent_id:
                parent_type = entity_type(parent)
                if parent_type == "IfcRepresentationMap":
                    index.aspect_parent_maps[aid].append(parent_id)
                elif parent_type in {
                    "IfcProductDefinitionShape", "IfcProductRepresentation",
                }:
                    index.aspect_parent_pds[aid].append(parent_id)
            if progress and (
                position % 250 == 0 or position == len(aspect_values)
            ):
                progress("indirect_shape_aspects", position, len(aspect_values))

        index.maps = _entities(model.by_type("IfcRepresentationMap"))
        for map_id, representation_map in index.maps.items():
            rid = entity_id(attr(representation_map, "MappedRepresentation"))
            if rid:
                index.representation_to_maps[rid].append(map_id)
            for aspect in attr(
                representation_map, "HasShapeAspects", ()
            ) or ():
                aspect_id = entity_id(aspect)
                if aspect_id and map_id not in index.aspect_parent_maps[aspect_id]:
                    index.aspect_parent_maps[aspect_id].append(map_id)

        index.type_products = _entities(model.by_type("IfcTypeProduct"))
        for type_id, type_product in index.type_products.items():
            for representation_map in attr(
                type_product, "RepresentationMaps", ()
            ) or ():
                map_id = entity_id(representation_map)
                if map_id:
                    index.map_to_type_products[map_id].append(type_id)
                    index.type_product_to_maps[type_id].append(map_id)
        for relationship in model.by_type("IfcRelDefinesByType"):
            type_id = entity_id(attr(relationship, "RelatingType"))
            if not type_id:
                continue
            for occurrence in attr(relationship, "RelatedObjects", ()) or ():
                occurrence_id = entity_id(occurrence)
                if occurrence_id:
                    index.type_to_occurrences[type_id].append(occurrence_id)

        index.mapped_items = _entities(model.by_type("IfcMappedItem"))
        for item_id, item in index.mapped_items.items():
            source_id = entity_id(attr(item, "MappingSource"))
            if source_id:
                index.map_to_usages[source_id].append(item_id)
        for relationship in model.by_type("IfcRelVoidsElement"):
            opening_id = entity_id(attr(relationship, "RelatedOpeningElement"))
            if opening_id:
                index.hosted_opening_ids.add(opening_id)

        representation_values = list(index.shape_representations.values())
        for position, representation in enumerate(representation_values, 1):
            if cancelled and cancelled():
                raise CancelledError(
                    "Scan cancelled while indexing mapped-item containment"
                )
            rid = entity_id(representation)
            context_id = entity_id(attr(representation, "ContextOfItems"))
            signature = (
                _normal(attr(representation, "RepresentationIdentifier")),
                _normal(attr(representation, "RepresentationType")),
            )
            if context_id in index.contexts:
                index.semantic_contexts[signature][context_id] += 1
            for item in attr(representation, "Items", ()) or ():
                item_id = entity_id(item)
                if item_id in index.mapped_items and rid:
                    index.item_to_representations[item_id].append(rid)
            if progress and (
                position % 250 == 0 or position == len(representation_values)
            ):
                progress(
                    "indirect_representation_index",
                    position,
                    len(representation_values),
                )
        return index

    def products_for_pds(self, pds_ids: Iterable[int]) -> set[int]:
        return {
            product_id
            for pds_id in pds_ids
            for product_id in self.pds_to_products.get(pds_id, ())
        }

    def products_for_representation(
        self,
        representation_id: int,
        visited_maps: set[int] | None = None,
    ) -> set[int]:
        product_ids = self.products_for_pds(
            self.representation_to_pds.get(representation_id, ())
        )
        for aspect_id in self.representation_to_aspects.get(
            representation_id, ()
        ):
            product_ids.update(
                self.products_for_pds(self.aspect_parent_pds.get(aspect_id, ()))
            )
            for map_id in self.aspect_parent_maps.get(aspect_id, ()):
                product_ids.update(self.products_for_map(map_id, visited_maps))
        for map_id in self.representation_to_maps.get(representation_id, ()):
            product_ids.update(self.products_for_map(map_id, visited_maps))
        return product_ids

    def products_for_map(
        self, map_id: int, visited_maps: set[int] | None = None,
    ) -> set[int]:
        if map_id in self._map_products_cache:
            return set(self._map_products_cache[map_id])
        visited = set(visited_maps or ())
        if map_id in visited:
            return set()
        visited.add(map_id)
        result: set[int] = set()
        for type_id in self.map_to_type_products.get(map_id, ()):
            result.update(self.type_to_occurrences.get(type_id, ()))
        for item_id in self.map_to_usages.get(map_id, ()):
            for outer_rep_id in self.item_to_representations.get(item_id, ()):
                result.update(
                    self.products_for_representation(outer_rep_id, visited)
                )
        self._map_products_cache[map_id] = set(result)
        return result

    def usage_outer_representations(self, map_ids: Iterable[int]) -> set[int]:
        return {
            representation_id
            for map_id in map_ids
            for item_id in self.map_to_usages.get(map_id, ())
            for representation_id in self.item_to_representations.get(item_id, ())
        }

    def type_owned_map_evidence(
        self, map_ids: Iterable[int], signature: tuple[str, str],
    ) -> tuple[set[int], set[int], set[int]]:
        """Return owners, compatible semantic peers, and sibling hierarchy roots."""
        owner_ids = {
            type_id
            for map_id in map_ids
            for type_id in self.map_to_type_products.get(map_id, ())
        }
        peer_contexts = {
            context_id
            for context_id in self.semantic_contexts.get(signature, ())
            if context_id in self.contexts
        }
        body_roots: set[int] = set()
        for type_id in owner_ids:
            for sibling_map_id in self.type_product_to_maps.get(type_id, ()):
                sibling_map = self.maps.get(sibling_map_id)
                sibling = attr(sibling_map, "MappedRepresentation")
                if _normal(attr(sibling, "RepresentationIdentifier")) != "body":
                    continue
                context_id = entity_id(attr(sibling, "ContextOfItems"))
                info = self.context_info.get(context_id)
                if info:
                    body_roots.add(info.parent_step_id or info.step_id)
        return owner_ids, peer_contexts, body_roots


def _supported_signature(rep: Any) -> tuple[str, str]:
    return (
        _normal(attr(rep, "RepresentationIdentifier")),
        _normal(attr(rep, "RepresentationType")),
    )


def _compatible(info: ContextInfo, signature: tuple[str, str]) -> bool:
    identifier, representation_type = signature
    context_identifier = _normal(info.identifier)
    context_type = _normal(info.context_type)
    target_view = str(info.target_view or "").upper()
    if not info.connected_to_project or context_identifier != identifier:
        return False
    if identifier == "body" and representation_type in {
        "sweptsolid", "tessellation",
    }:
        return (
            context_type == "model"
            and info.dimension == 3
            and target_view in {"", "MODEL_VIEW"}
        )
    if identifier == "footprint" and representation_type == "curve2d":
        # IFC subcontexts inherit the parent coordinate-space dimension. A
        # PLAN_VIEW FootPrint is semantically two-dimensional even when the
        # inherited parent context reports dimension 3.
        return (
            info.dimension in {2, 3}
            and target_view in {"", "PLAN_VIEW", "MODEL_VIEW"}
        )
    return False


def _classification(
    representation_id: int,
    signature: tuple[str, str],
    index: RepresentationGraphIndex,
) -> tuple[RepresentationClassification, list[str]]:
    pds_ids = set(index.representation_to_pds.get(representation_id, ()))
    aspect_ids = set(index.representation_to_aspects.get(representation_id, ()))
    map_ids = set(index.representation_to_maps.get(representation_id, ()))
    evidence: list[str] = []
    if signature not in SUPPORTED_SIGNATURES:
        return (
            RepresentationClassification.UNSUPPORTED,
            [f"Signature {signature[0] or '-'} / {signature[1] or '-'} is outside the approved scope"],
        )
    ownership_kinds = sum(bool(values) for values in (pds_ids, aspect_ids, map_ids))
    if ownership_kinds > 1 or len(pds_ids) > 1 or len(map_ids) > 1:
        return (
            RepresentationClassification.AMBIGUOUS,
            ["Representation has multiple conflicting ownership paths"],
        )
    if aspect_ids:
        parent_pds = {
            value
            for aspect_id in aspect_ids
            for value in index.aspect_parent_pds.get(aspect_id, ())
        }
        parent_maps = {
            value
            for aspect_id in aspect_ids
            for value in index.aspect_parent_maps.get(aspect_id, ())
        }
        if (parent_pds and parent_maps) or len(aspect_ids) > 1:
            return (
                RepresentationClassification.AMBIGUOUS,
                ["Shape-aspect representation has conflicting parent paths"],
            )
        if parent_pds:
            evidence.append("Shape aspect is linked to an IfcProductDefinitionShape")
            return RepresentationClassification.SHAPE_ASPECT_PRODUCT, evidence
        if parent_maps:
            evidence.append("Shape aspect is linked to an IfcRepresentationMap")
            return (
                RepresentationClassification.SHAPE_ASPECT_REPRESENTATION_MAP,
                evidence,
            )
        return (
            RepresentationClassification.ORPHANED,
            ["Shape aspect has no traceable product definition or representation map"],
        )
    if pds_ids:
        evidence.append("Representation is directly owned by an IfcProductDefinitionShape")
        return RepresentationClassification.DIRECT_PRODUCT, evidence
    if map_ids:
        evidence.append("Representation is the MappedRepresentation of an IfcRepresentationMap")
        return RepresentationClassification.REPRESENTATION_MAP, evidence
    return (
        RepresentationClassification.ORPHANED,
        ["Representation has no supported product, shape-aspect or map ownership path"],
    )


def _risk(classification: RepresentationClassification, usage_count: int) -> tuple[str, str, str]:
    if classification is RepresentationClassification.DIRECT_PRODUCT:
        return "Medium to High", "High", "High"
    if classification in {
        RepresentationClassification.REPRESENTATION_MAP,
        RepresentationClassification.SHAPE_ASPECT_REPRESENTATION_MAP,
    }:
        return (
            "Medium",
            "High" if usage_count > 1 else "Medium to High",
            "High" if usage_count else "Medium",
        )
    if classification is RepresentationClassification.SHAPE_ASPECT_PRODUCT:
        return "Low to Medium", "Medium", "Medium"
    if classification is RepresentationClassification.ORPHANED:
        return "Low", "Low to Unknown", "Low"
    return "Unknown", "Unknown", "Review"


def _resolve(
    rep: Any,
    diagnosis: Diagnosis,
    index: RepresentationGraphIndex,
) -> None:
    signature = _supported_signature(rep)
    eligible = {
        cid: info
        for cid, info in index.context_info.items()
        if _compatible(info, signature)
    }
    if not eligible:
        diagnosis.conflicts.append("No compatible project-connected context exists")
        return

    scores: dict[int, int] = defaultdict(int)
    reasons: dict[int, list[str]] = defaultdict(list)
    owner_rep_ids: set[int] = set()
    map_ids: set[int] = set(index.representation_to_maps.get(
        diagnosis.representation_step_id, ()
    ))
    for aspect_id in index.representation_to_aspects.get(
        diagnosis.representation_step_id, ()
    ):
        map_ids.update(index.aspect_parent_maps.get(aspect_id, ()))
        for pds_id in index.aspect_parent_pds.get(aspect_id, ()):
            owner_rep_ids.update(index.pds_to_representations.get(pds_id, ()))
    for pds_id in index.representation_to_pds.get(
        diagnosis.representation_step_id, ()
    ):
        owner_rep_ids.update(index.pds_to_representations.get(pds_id, ()))

    sibling_contexts: set[int] = set()
    for sibling_id in owner_rep_ids:
        if sibling_id == diagnosis.representation_step_id:
            continue
        sibling = index.shape_representations.get(sibling_id)
        if not sibling or _supported_signature(sibling) != signature:
            continue
        context_id = entity_id(attr(sibling, "ContextOfItems"))
        if context_id in eligible:
            sibling_contexts.add(context_id)
            scores[context_id] += 80
            reasons[context_id].append(
                "Exact matching sibling representation uses this context"
            )
    if len(sibling_contexts) > 1:
        diagnosis.conflicts.append("Matching siblings use conflicting contexts")

    outer_ids = index.usage_outer_representations(map_ids)
    usage_contexts: list[int] = []
    for outer_id in outer_ids:
        outer = index.shape_representations.get(outer_id)
        context_id = entity_id(attr(outer, "ContextOfItems")) if outer else None
        if context_id in eligible:
            usage_contexts.append(context_id)
    unique_usage_contexts = set(usage_contexts)
    if usage_contexts and len(unique_usage_contexts) == 1:
        context_id = usage_contexts[0]
        scores[context_id] += 90
        reasons[context_id].append(
            f"All {len(usage_contexts):,} valid representation-map usage(s) agree"
        )
    elif len(unique_usage_contexts) > 1:
        diagnosis.conflicts.append("Representation-map usages have conflicting contexts")

    observed = index.semantic_contexts.get(signature, Counter())
    for context_id, count in observed.items():
        if context_id in eligible:
            scores[context_id] += min(65, 40 + count * 5)
            reasons[context_id].append(
                f"{count:,} exact semantic peer representation(s) use this context"
            )
    if len({cid for cid in observed if cid in eligible}) > 1:
        diagnosis.conflicts.append("Semantic peers use more than one compatible context")

    type_owner_ids: set[int] = set()
    type_peer_contexts: set[int] = set()
    type_body_roots: set[int] = set()
    type_owned_footprint = (
        diagnosis.classification is RepresentationClassification.REPRESENTATION_MAP
        and signature == ("footprint", "curve2d")
    )
    if type_owned_footprint:
        (
            type_owner_ids,
            type_peer_contexts,
            type_body_roots,
        ) = index.type_owned_map_evidence(map_ids, signature)
        if len(type_owner_ids) > 1:
            diagnosis.conflicts.append(
                "Representation map has multiple type-product owners"
            )
        elif len(type_owner_ids) == 1:
            owner_id = next(iter(type_owner_ids))
            diagnosis.evidence.append(
                f"Representation map is owned by IfcTypeProduct #{owner_id}"
            )
        if len(type_peer_contexts) == 1:
            context_id = next(iter(type_peer_contexts))
            if context_id in eligible:
                scores[context_id] += 100
                reasons[context_id].append(
                    "All valid FootPrint / Curve2D semantic peers use this context"
                )
        elif len(type_peer_contexts) > 1:
            diagnosis.conflicts.append(
                "Valid FootPrint / Curve2D peers use conflicting contexts"
            )

    for context_id, info in eligible.items():
        scores[context_id] += 30
        reasons[context_id].append(
            "Context identifier matches the representation identifier"
        )
        scores[context_id] += 10
        reasons[context_id].append("Coordinate-space semantics are compatible")
        if str(info.target_view or "").upper() in {
            "", "MODEL_VIEW", "PLAN_VIEW",
        }:
            scores[context_id] += 10
            reasons[context_id].append("Target view is compatible")

    ranked = sorted(scores, key=lambda context_id: (-scores[context_id], context_id))
    diagnosis.candidates = [eligible[cid] for cid in ranked]
    diagnosis.decision_trace = [
        {
            "context_step_id": cid,
            "score": scores[cid],
            "evidence": list(reasons[cid]),
            "conflicts": list(diagnosis.conflicts),
            "selected": False,
        }
        for cid in ranked
    ]
    if not ranked:
        diagnosis.conflicts.append("No candidate context received evidence")
        return
    best = ranked[0]
    best_score = scores[best]
    second_score = scores[ranked[1]] if len(ranked) > 1 else -1
    if second_score == best_score or best_score - second_score < 20:
        diagnosis.status = Status.AMBIGUOUS
        diagnosis.confidence_level = ConfidenceLevel.AMBIGUOUS
        diagnosis.confidence = min(0.69, best_score / 180)
        diagnosis.conflicts.append("Leading candidates are tied or too close")
        return
    if diagnosis.conflicts:
        diagnosis.status = Status.AMBIGUOUS
        diagnosis.confidence_level = ConfidenceLevel.AMBIGUOUS
        diagnosis.confidence = min(0.69, best_score / 180)
        return

    map_classification = diagnosis.classification in {
        RepresentationClassification.REPRESENTATION_MAP,
        RepresentationClassification.SHAPE_ASPECT_REPRESENTATION_MAP,
    }
    type_owned_footprint_proven = False
    if type_owned_footprint and len(type_owner_ids) == 1 and len(type_peer_contexts) == 1:
        peer_context_id = next(iter(type_peer_contexts))
        peer_info = index.context_info.get(peer_context_id)
        peer_root = (
            peer_info.parent_step_id or peer_info.step_id if peer_info else None
        )
        type_owned_footprint_proven = (
            peer_context_id == best
            and len(type_body_roots) == 1
            and peer_root in type_body_roots
        )
        if type_owned_footprint_proven:
            reasons[best].append(
                "Type-owned map and sibling Body map share one project context hierarchy"
            )
            diagnosis.evidence.append(
                "A valid type owner proves meaningful reusable geometry even without occurrences"
            )
        else:
            diagnosis.conflicts.append(
                "Type ownership or sibling Body context hierarchy did not prove the candidate"
            )

    if map_classification and not usage_contexts and not type_owned_footprint_proven:
        diagnosis.confidence_level = ConfidenceLevel.LOW
        diagnosis.confidence = min(0.49, best_score / 200)
        diagnosis.conflicts.append(
            "No valid outer representation-map usage context was found"
        )
        return
    if (
        map_classification
        and len(unique_usage_contexts) != 1
        and not type_owned_footprint_proven
    ):
        diagnosis.status = Status.AMBIGUOUS
        diagnosis.confidence_level = ConfidenceLevel.AMBIGUOUS
        return

    if best_score >= 80:
        diagnosis.status = Status.SAFE
        diagnosis.confidence_level = ConfidenceLevel.HIGH
        diagnosis.confidence = max(0.80, min(0.99, best_score / 150))
        diagnosis.proposed_context = eligible[best]
        diagnosis.evidence.extend(reasons[best])
        diagnosis.proposed_action = "High-confidence auto-repair"
        for trace in diagnosis.decision_trace:
            if trace["context_step_id"] == best:
                trace["selected"] = True
                trace["tie_break_reason"] = "Unique highest compatible semantic score"
    elif best_score >= 50:
        diagnosis.status = Status.WARNING
        diagnosis.confidence_level = ConfidenceLevel.MEDIUM
        diagnosis.confidence = min(0.79, best_score / 150)
    else:
        diagnosis.confidence_level = ConfidenceLevel.LOW
        diagnosis.confidence = min(0.49, best_score / 150)


def classify_missing_contexts(
    model: Any,
    *,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
    timings: dict[str, float] | None = None,
) -> tuple[list[Diagnosis], RepresentationGraphIndex]:
    mark = time.perf_counter()
    index = RepresentationGraphIndex.build(
        model, progress=progress, cancelled=cancelled
    )
    if timings is not None:
        timings["indirect_index_build"] = time.perf_counter() - mark

    missing = [
        rep for rep in index.shape_representations.values()
        if entity_id(attr(rep, "ContextOfItems")) not in index.contexts
    ]
    diagnoses: list[Diagnosis] = []
    mark = time.perf_counter()
    for position, rep in enumerate(missing, 1):
        if cancelled and cancelled():
            raise CancelledError(
                "Scan cancelled while classifying missing representation contexts"
            )
        rid = entity_id(rep) or 0
        signature = _supported_signature(rep)
        classification, classification_evidence = _classification(
            rid, signature, index
        )
        product_ids = index.products_for_representation(rid)
        products = [
            index.products[product_id]
            for product_id in sorted(product_ids)
            if product_id in index.products
        ]
        product = products[0] if len(products) == 1 else None
        map_ids = set(index.representation_to_maps.get(rid, ()))
        for aspect_id in index.representation_to_aspects.get(rid, ()):
            map_ids.update(index.aspect_parent_maps.get(aspect_id, ()))
        usage_count = sum(len(index.map_to_usages.get(mid, ())) for mid in map_ids)
        class_counts = Counter(entity_type(item) or "Unknown" for item in products)
        items = list(attr(rep, "Items", ()) or ())
        rendering, downstream, priority = _risk(classification, usage_count)
        diagnosis = Diagnosis(
            representation_step_id=rid,
            representation_identifier=attr(rep, "RepresentationIdentifier"),
            representation_type=attr(rep, "RepresentationType"),
            item_count=len(items),
            item_classes=[entity_type(item) or "Unknown" for item in items],
            current_context_step_id=entity_id(attr(rep, "ContextOfItems")),
            product_class=(
                entity_type(product)
                if product is not None else
                ("Multiple product classes" if products else None)
            ),
            product_step_id=entity_id(product),
            product_global_id=attr(product, "GlobalId"),
            product_name=attr(product, "Name"),
            product_tag=attr(product, "Tag"),
            owner_step_id=(
                (index.representation_to_aspects.get(rid) or
                 index.representation_to_maps.get(rid) or
                 index.representation_to_pds.get(rid) or [None])[0]
            ),
            classification=classification,
            confidence_level=ConfidenceLevel.LOW,
            usage_count=usage_count,
            ultimate_product_count=len(products),
            ultimate_product_classes=dict(class_counts),
            rendering_risk=rendering,
            downstream_processing_risk=downstream,
            repair_priority=priority,
            evidence=list(classification_evidence),
        )
        diagnosis.rule_id = RULE_BY_CLASSIFICATION.get(classification)
        if (
            classification is RepresentationClassification.REPRESENTATION_MAP
            and signature == ("footprint", "curve2d")
        ):
            diagnosis.rule_id = "REPRESENTATION_MAP_FOOTPRINT_MISSING_CONTEXT_V1"
        if classification is RepresentationClassification.UNSUPPORTED:
            diagnosis.status = Status.NOT_REPAIRABLE
            diagnosis.proposed_action = "Unsupported - report only"
        elif classification is RepresentationClassification.ORPHANED:
            diagnosis.status = Status.NOT_REPAIRABLE
            diagnosis.proposed_action = "Orphaned - report only"
        elif classification is RepresentationClassification.AMBIGUOUS:
            diagnosis.status = Status.AMBIGUOUS
            diagnosis.confidence_level = ConfidenceLevel.AMBIGUOUS
            diagnosis.proposed_action = "Ambiguous - report only"
        else:
            _resolve(rep, diagnosis, index)
            if (
                diagnosis.classification
                is RepresentationClassification.DIRECT_PRODUCT
                and diagnosis.product_class == "IfcOpeningElement"
                and diagnosis.product_step_id not in index.hosted_opening_ids
            ):
                diagnosis.status = Status.NOT_REPAIRABLE
                diagnosis.confidence_level = ConfidenceLevel.LOW
                diagnosis.proposed_context = None
                diagnosis.proposed_action = "Unhosted opening - report only"
                diagnosis.conflicts.append(
                    "Opening is not connected to a host through IfcRelVoidsElement"
                )
        diagnoses.append(diagnosis)
        if progress and (position % 250 == 0 or position == len(missing)):
            progress("indirect_classification", position, len(missing))
    if timings is not None:
        timings["indirect_classification"] = time.perf_counter() - mark
    return diagnoses, index


def is_repairable_in_mode(diagnosis: Diagnosis, mode: str) -> bool:
    if diagnosis.status is not Status.SAFE:
        return False
    if diagnosis.confidence_level is not ConfidenceLevel.HIGH:
        return False
    normalized = mode.strip().casefold()
    if normalized == "audit":
        return False
    if normalized in {"safe", "targeted"}:
        return diagnosis.classification is RepresentationClassification.DIRECT_PRODUCT
    if normalized in {"extended", "advanced"}:
        return diagnosis.classification in {
            RepresentationClassification.DIRECT_PRODUCT,
            RepresentationClassification.SHAPE_ASPECT_PRODUCT,
            RepresentationClassification.REPRESENTATION_MAP,
            RepresentationClassification.SHAPE_ASPECT_REPRESENTATION_MAP,
        }
    return False
