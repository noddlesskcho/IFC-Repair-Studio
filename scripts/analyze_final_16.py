from __future__ import annotations

import argparse
import hashlib
import html
import json
import mmap
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import ifcopenshell

from ifc_context_repair.step_patch import (
    apply_patch_plan,
    build_patch_plan,
    source_fingerprint,
    validate_patch_plan,
)
from ifc_context_repair.target_verification import (
    verify_step_envelope,
    verify_targeted_output,
)


EXPECTED_TARGETS = 16
TARGET_IDENTIFIER = "footprint"
TARGET_TYPE = "curve2d"
RULE_ID = "REPRESENTATION_MAP_FOOTPRINT_MISSING_CONTEXT_V1"
ENTITY_LINE = re.compile(rb"^\s*#(\d+)\s*=", re.I)
SHAPE_LINE = re.compile(
    rb"^\s*#(\d+)\s*=\s*IFCSHAPEREPRESENTATION\s*\(\s*(\$|#\d+)",
    re.I,
)


def normal(value: object) -> str:
    return str(value or "").strip().casefold()


def step_id(entity: Any) -> int:
    try:
        return int(entity.id()) if entity is not None else 0
    except (AttributeError, TypeError, ValueError):
        return 0


def entity_type(entity: Any) -> str:
    try:
        return str(entity.is_a()) if entity is not None else ""
    except (AttributeError, TypeError):
        return ""


def value(entity: Any, name: str, default: Any = None) -> Any:
    try:
        result = getattr(entity, name)
    except (AttributeError, RuntimeError):
        return default
    return default if result is None else result


def entity_label(entity: Any) -> dict[str, Any]:
    if entity is None:
        return {}
    return {
        "step_id": step_id(entity),
        "entity_type": entity_type(entity),
        "global_id": str(value(entity, "GlobalId", "") or ""),
        "name": str(value(entity, "Name", "") or ""),
    }


def safe_scalar(entity: Any, name: str) -> Any:
    item = value(entity, name)
    if item is None:
        return None
    if hasattr(item, "id"):
        return f"#{step_id(item)}"
    if isinstance(item, (tuple, list)):
        return [f"#{step_id(part)}" if hasattr(part, "id") else str(part) for part in item]
    return str(item)


def direct_entities(item: Any) -> Iterable[Any]:
    if hasattr(item, "id") and hasattr(item, "is_a"):
        yield item
        return
    if isinstance(item, (tuple, list)):
        for child in item:
            yield from direct_entities(child)


def direct_reference_trace(entity: Any) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for position in range(len(entity)):
        try:
            attribute = entity.attribute_name(position)
            attribute_value = entity[position]
        except (IndexError, RuntimeError):
            continue
        for referenced in direct_entities(attribute_value):
            trace.append({
                "attribute": attribute,
                "referenced_step_id": step_id(referenced),
                "referenced_entity_type": entity_type(referenced),
            })
    return trace


def reference_attributes(entity: Any, target_id: int) -> list[str]:
    attributes: list[str] = []
    for position in range(len(entity)):
        try:
            attribute = entity.attribute_name(position)
            refs = {step_id(part) for part in direct_entities(entity[position])}
        except (IndexError, RuntimeError):
            continue
        if target_id in refs:
            attributes.append(attribute)
    return attributes


def sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def context_root(context: Any) -> int:
    current = context
    visited: set[int] = set()
    while current is not None and step_id(current) not in visited:
        current_id = step_id(current)
        visited.add(current_id)
        parent = value(current, "ParentContext")
        if parent is None:
            return current_id
        current = parent
    return step_id(context)


def context_record(context: Any, project_context_ids: set[int]) -> dict[str, Any]:
    parent = value(context, "ParentContext")
    dimension = value(context, "CoordinateSpaceDimension")
    if dimension is None and parent is not None:
        dimension = value(parent, "CoordinateSpaceDimension")
    root_id = context_root(context)
    return {
        "step_id": step_id(context),
        "entity_type": entity_type(context),
        "context_identifier": str(value(context, "ContextIdentifier", "") or ""),
        "context_type": str(
            value(context, "ContextType", "")
            or value(parent, "ContextType", "")
            or ""
        ),
        "coordinate_space_dimension": dimension,
        "target_view": str(value(context, "TargetView", "") or ""),
        "parent_context": step_id(parent) or None,
        "root_context": root_id,
        "connected_to_project": root_id in project_context_ids,
        "world_coordinate_system": safe_scalar(context, "WorldCoordinateSystem")
        or safe_scalar(parent, "WorldCoordinateSystem"),
        "true_north": safe_scalar(context, "TrueNorth") or safe_scalar(parent, "TrueNorth"),
        "precision": safe_scalar(context, "Precision") or safe_scalar(parent, "Precision"),
        "semantic_key": [
            normal(value(context, "ContextIdentifier")),
            normal(value(context, "ContextType") or value(parent, "ContextType")),
            dimension,
            str(value(context, "TargetView", "") or "").upper(),
            root_id,
        ],
    }


def compatible_footprint_context(record: dict[str, Any]) -> bool:
    # IfcGeometricRepresentationSubContext derives CoordinateSpaceDimension from
    # its parent. Revit therefore commonly reports dimension 3 for a PLAN_VIEW
    # FootPrint subcontext whose represented curves remain two-dimensional.
    dimension = record["coordinate_space_dimension"]
    target_view = record["target_view"].upper()
    return (
        record["connected_to_project"]
        and normal(record["context_identifier"]) == TARGET_IDENTIFIER
        and normal(record["context_type"]) == "model"
        and dimension in {2, 3}
        # Revit can export a valid FootPrint subcontext as MODEL_VIEW. This is
        # accepted only because the identifier/type/dimension/project hierarchy
        # checks above still apply; equivalent valid representations must also
        # prove the exact entity before a repair is authorised.
        and target_view in {"", "PLAN_VIEW", "MODEL_VIEW"}
    )


def representation_signature(representation: Any) -> tuple[str, str]:
    return (
        normal(value(representation, "RepresentationIdentifier")),
        normal(value(representation, "RepresentationType")),
    )


def product_record(product: Any) -> dict[str, Any]:
    return {
        **entity_label(product),
        "object_type": str(value(product, "ObjectType", "") or ""),
        "predefined_type": str(value(product, "PredefinedType", "") or ""),
    }


def owner_type_record(owner: Any, map_index: int) -> dict[str, Any]:
    return {
        **entity_label(owner),
        "predefined_type": str(value(owner, "PredefinedType", "") or ""),
        "representation_maps_index_position": map_index,
    }


@dataclass
class AuditIndexes:
    shape_representations: dict[int, Any]
    maps: dict[int, Any]
    shape_representation_to_maps: dict[int, list[int]]
    representation_map_to_type_products: dict[int, list[tuple[int, int]]]
    representation_map_to_mapped_items: dict[int, list[int]]
    mapped_items: dict[int, Any]
    mapped_item_to_outer_representations: dict[int, list[int]]
    outer_representation_to_product_definition_shapes: dict[int, list[int]]
    product_definition_shape_to_products: dict[int, list[int]]
    type_products: dict[int, Any]
    type_product_to_rel_defines_by_type: dict[int, list[int]]
    rel_defines_by_type_to_occurrences: dict[int, list[int]]
    products: dict[int, Any]
    product_to_type_products: dict[int, list[int]]
    contexts: dict[int, Any]
    context_records: dict[int, dict[str, Any]]
    context_semantic_index: dict[tuple[Any, ...], list[int]]
    reverse_references: dict[int, list[dict[str, Any]]]
    outbound_references: dict[int, list[dict[str, Any]]]


def build_indexes(model: Any) -> AuditIndexes:
    shapes = {step_id(item): item for item in model.by_type("IfcShapeRepresentation")}
    maps = {step_id(item): item for item in model.by_type("IfcRepresentationMap")}
    shape_to_maps: dict[int, list[int]] = defaultdict(list)
    for map_id, representation_map in maps.items():
        mapped_rep_id = step_id(value(representation_map, "MappedRepresentation"))
        if mapped_rep_id:
            shape_to_maps[mapped_rep_id].append(map_id)

    type_products = {step_id(item): item for item in model.by_type("IfcTypeProduct")}
    map_to_types: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for type_id, type_product in type_products.items():
        for position, representation_map in enumerate(
            value(type_product, "RepresentationMaps", ()) or (), 1
        ):
            map_to_types[step_id(representation_map)].append((type_id, position))

    mapped_items = {step_id(item): item for item in model.by_type("IfcMappedItem")}
    map_to_items: dict[int, list[int]] = defaultdict(list)
    for item_id, item in mapped_items.items():
        map_to_items[step_id(value(item, "MappingSource"))].append(item_id)

    item_to_outer: dict[int, list[int]] = defaultdict(list)
    for representation_id, representation in shapes.items():
        for item in value(representation, "Items", ()) or ():
            item_id = step_id(item)
            if item_id in mapped_items:
                item_to_outer[item_id].append(representation_id)

    pds_to_products: dict[int, list[int]] = defaultdict(list)
    rep_to_pds: dict[int, list[int]] = defaultdict(list)
    products = {step_id(item): item for item in model.by_type("IfcProduct")}
    for product_id, product in products.items():
        pds = value(product, "Representation")
        pds_id = step_id(pds)
        if not pds_id:
            continue
        pds_to_products[pds_id].append(product_id)
        for representation in value(pds, "Representations", ()) or ():
            rep_to_pds[step_id(representation)].append(pds_id)

    type_to_rels: dict[int, list[int]] = defaultdict(list)
    rel_to_occurrences: dict[int, list[int]] = defaultdict(list)
    product_to_types: dict[int, list[int]] = defaultdict(list)
    for relationship in model.by_type("IfcRelDefinesByType"):
        rel_id = step_id(relationship)
        type_id = step_id(value(relationship, "RelatingType"))
        if type_id:
            type_to_rels[type_id].append(rel_id)
        for occurrence in value(relationship, "RelatedObjects", ()) or ():
            occurrence_id = step_id(occurrence)
            if occurrence_id:
                rel_to_occurrences[rel_id].append(occurrence_id)
                product_to_types[occurrence_id].append(type_id)

    project_context_ids: set[int] = set()
    for project in model.by_type("IfcProject"):
        project_context_ids.update(
            step_id(context)
            for context in value(project, "RepresentationContexts", ()) or ()
        )
    contexts: dict[int, Any] = {}
    for context in model.by_type("IfcGeometricRepresentationContext"):
        contexts[step_id(context)] = context
    for context in model.by_type("IfcGeometricRepresentationSubContext"):
        contexts[step_id(context)] = context
    context_records = {
        context_id: context_record(context, project_context_ids)
        for context_id, context in contexts.items()
    }
    semantic_index: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for context_id, record in context_records.items():
        semantic_index[tuple(record["semantic_key"])].append(context_id)

    return AuditIndexes(
        shapes,
        maps,
        dict(shape_to_maps),
        dict(map_to_types),
        dict(map_to_items),
        mapped_items,
        dict(item_to_outer),
        dict(rep_to_pds),
        dict(pds_to_products),
        type_products,
        dict(type_to_rels),
        dict(rel_to_occurrences),
        products,
        dict(product_to_types),
        contexts,
        context_records,
        {key: sorted(ids) for key, ids in semantic_index.items()},
        {},
        {},
    )


def target_representations(indexes: AuditIndexes) -> list[Any]:
    return sorted(
        (
            representation
            for representation_id, representation in indexes.shape_representations.items()
            if value(representation, "ContextOfItems") is None
            and representation_signature(representation)
            == (TARGET_IDENTIFIER, TARGET_TYPE)
            and representation_id in indexes.shape_representation_to_maps
        ),
        key=step_id,
    )


def recursively_used_map_ids(
    representation_ids: Iterable[int],
    indexes: AuditIndexes,
    visited_representations: set[int] | None = None,
) -> set[int]:
    visited = set(visited_representations or ())
    result: set[int] = set()
    for representation_id in representation_ids:
        if representation_id in visited:
            continue
        visited.add(representation_id)
        representation = indexes.shape_representations.get(representation_id)
        if representation is None:
            continue
        for item in value(representation, "Items", ()) or ():
            item_id = step_id(item)
            mapped_item = indexes.mapped_items.get(item_id)
            if mapped_item is None:
                continue
            map_id = step_id(value(mapped_item, "MappingSource"))
            if not map_id:
                continue
            result.add(map_id)
            mapped_rep = value(indexes.maps.get(map_id), "MappedRepresentation")
            mapped_rep_id = step_id(mapped_rep)
            if mapped_rep_id:
                result.update(
                    recursively_used_map_ids([mapped_rep_id], indexes, visited)
                )
    return result


def occurrence_representation_ids(product: Any) -> list[int]:
    pds = value(product, "Representation")
    return [
        step_id(representation)
        for representation in value(pds, "Representations", ()) or ()
        if step_id(representation)
    ]


def populate_reference_indexes(
    model: Any,
    relevant_entities: dict[int, Any],
    indexes: AuditIndexes,
) -> None:
    for target_id, target in relevant_entities.items():
        inbound: list[dict[str, Any]] = []
        try:
            inverse_entities = model.get_inverse(target)
        except (AttributeError, RuntimeError):
            inverse_entities = ()
        for referrer in inverse_entities:
            inbound.append({
                "referrer_step_id": step_id(referrer),
                "referrer_entity_type": entity_type(referrer),
                "attributes": reference_attributes(referrer, target_id),
            })
        indexes.reverse_references[target_id] = sorted(
            inbound,
            key=lambda item: (item["referrer_step_id"], item["referrer_entity_type"]),
        )
        indexes.outbound_references[target_id] = direct_reference_trace(target)


def map_usage_trace(map_id: int, indexes: AuditIndexes) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item_id in sorted(indexes.representation_map_to_mapped_items.get(map_id, ())):
        outer_ids = indexes.mapped_item_to_outer_representations.get(item_id, ())
        if not outer_ids:
            result.append({
                "mapped_item_step_id": item_id,
                "outer_representation": None,
                "products": [],
            })
            continue
        for outer_id in sorted(outer_ids):
            outer = indexes.shape_representations.get(outer_id)
            product_ids = {
                product_id
                for pds_id in indexes.outer_representation_to_product_definition_shapes.get(
                    outer_id, ()
                )
                for product_id in indexes.product_definition_shape_to_products.get(pds_id, ())
            }
            result.append({
                "mapped_item_step_id": item_id,
                "outer_representation": {
                    "step_id": outer_id,
                    "representation_identifier": str(
                        value(outer, "RepresentationIdentifier", "") or ""
                    ),
                    "representation_type": str(
                        value(outer, "RepresentationType", "") or ""
                    ),
                    "context_of_items": step_id(value(outer, "ContextOfItems")) or None,
                },
                "products": [
                    product_record(indexes.products[product_id])
                    for product_id in sorted(product_ids)
                    if product_id in indexes.products
                ],
            })
    return result


def type_occurrence_trace(
    type_id: int, map_id: int, indexes: AuditIndexes
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for relationship_id in indexes.type_product_to_rel_defines_by_type.get(type_id, ()):
        for occurrence_id in indexes.rel_defines_by_type_to_occurrences.get(
            relationship_id, ()
        ):
            if occurrence_id in seen:
                continue
            seen.add(occurrence_id)
            occurrence = indexes.products.get(occurrence_id)
            representation_ids = occurrence_representation_ids(occurrence)
            used_maps = recursively_used_map_ids(representation_ids, indexes)
            footprint_contexts = sorted({
                step_id(value(indexes.shape_representations.get(rep_id), "ContextOfItems"))
                for rep_id in representation_ids
                if representation_signature(indexes.shape_representations.get(rep_id))
                == (TARGET_IDENTIFIER, TARGET_TYPE)
                and step_id(value(indexes.shape_representations.get(rep_id), "ContextOfItems"))
            })
            result.append({
                **product_record(occurrence),
                "rel_defines_by_type_step_id": relationship_id,
                "uses_target_map_directly_or_indirectly": map_id in used_maps,
                "valid_occurrence_footprint_contexts": footprint_contexts,
            })
    return sorted(result, key=lambda item: item["step_id"])


def equivalent_footprints(indexes: AuditIndexes) -> dict[str, Any]:
    valid: list[Any] = [
        rep
        for rep in indexes.shape_representations.values()
        if representation_signature(rep) == (TARGET_IDENTIFIER, TARGET_TYPE)
        and step_id(value(rep, "ContextOfItems"))
    ]
    context_counts = Counter(
        step_id(value(rep, "ContextOfItems")) for rep in valid
    )
    owner_groups: Counter[tuple[str, str, int]] = Counter()
    for rep in valid:
        rep_id = step_id(rep)
        context_id = step_id(value(rep, "ContextOfItems"))
        map_ids = indexes.shape_representation_to_maps.get(rep_id, ())
        if map_ids:
            for map_id in map_ids:
                owners = indexes.representation_map_to_type_products.get(map_id, ())
                if owners:
                    for type_id, _position in owners:
                        owner_groups[
                            ("REPRESENTATION_MAP", entity_type(indexes.type_products[type_id]), context_id)
                        ] += 1
                else:
                    owner_groups[("REPRESENTATION_MAP", "Unowned", context_id)] += 1
        pds_ids = indexes.outer_representation_to_product_definition_shapes.get(rep_id, ())
        if pds_ids:
            product_ids = {
                pid
                for pds_id in pds_ids
                for pid in indexes.product_definition_shape_to_products.get(pds_id, ())
            }
            for product_id in product_ids:
                owner_groups[
                    ("DIRECT_PRODUCT", entity_type(indexes.products[product_id]), context_id)
                ] += 1
        if not map_ids and not pds_ids:
            owner_groups[("OTHER", "Unknown", context_id)] += 1
    return {
        "count": len(valid),
        "context_counts": {str(key): count for key, count in sorted(context_counts.items())},
        "distinct_contexts": sorted(context_counts),
        "groups": [
            {
                "owner_type": owner_type,
                "owner_class": owner_class,
                "context_step_id": context_id,
                "count": count,
            }
            for (owner_type, owner_class, context_id), count in sorted(owner_groups.items())
        ],
    }


def sibling_maps_for_owner(
    owner: Any, target_map_id: int, indexes: AuditIndexes
) -> list[dict[str, Any]]:
    siblings: list[dict[str, Any]] = []
    for position, representation_map in enumerate(
        value(owner, "RepresentationMaps", ()) or (), 1
    ):
        map_id = step_id(representation_map)
        mapped_rep = value(representation_map, "MappedRepresentation")
        context_id = step_id(value(mapped_rep, "ContextOfItems")) or None
        siblings.append({
            "map_step_id": map_id,
            "is_target_map": map_id == target_map_id,
            "index_position": position,
            "mapped_representation_step_id": step_id(mapped_rep),
            "representation_identifier": str(
                value(mapped_rep, "RepresentationIdentifier", "") or ""
            ),
            "representation_type": str(value(mapped_rep, "RepresentationType", "") or ""),
            "context_of_items": context_id,
            "semantic_context": (
                indexes.context_records.get(context_id) if context_id else None
            ),
        })
    return siblings


def analyse_case(
    representation: Any,
    indexes: AuditIndexes,
    candidates: list[dict[str, Any]],
    equivalent: dict[str, Any],
) -> dict[str, Any]:
    representation_id = step_id(representation)
    map_ids = sorted(indexes.shape_representation_to_maps.get(representation_id, ()))
    maps_trace: list[dict[str, Any]] = []
    all_owner_records: list[dict[str, Any]] = []
    all_usages: list[dict[str, Any]] = []
    all_occurrences: list[dict[str, Any]] = []
    all_siblings: list[dict[str, Any]] = []
    conflicts: list[str] = []

    for map_id in map_ids:
        map_entity = indexes.maps[map_id]
        owners = indexes.representation_map_to_type_products.get(map_id, ())
        owner_records: list[dict[str, Any]] = []
        for type_id, position in owners:
            owner = indexes.type_products[type_id]
            owner_record = owner_type_record(owner, position)
            owner_record["inbound_references"] = indexes.reverse_references.get(
                type_id, []
            )
            owner_record["outbound_references"] = indexes.outbound_references.get(
                type_id, []
            )
            owner_records.append(owner_record)
            all_owner_records.append(owner_record)
            occurrences = type_occurrence_trace(type_id, map_id, indexes)
            all_occurrences.extend(occurrences)
            all_siblings.extend(sibling_maps_for_owner(owner, map_id, indexes))
        usages = map_usage_trace(map_id, indexes)
        all_usages.extend(usages)
        maps_trace.append({
            "representation_map_step_id": map_id,
            "mapping_origin_step_id": step_id(value(map_entity, "MappingOrigin")) or None,
            "mapped_representation_step_id": representation_id,
            "owners": owner_records,
            "direct_mapped_usages": usages,
            "inbound_references": indexes.reverse_references.get(map_id, []),
            "outbound_references": indexes.outbound_references.get(map_id, []),
        })

    owner_ids = {record["step_id"] for record in all_owner_records}
    product_reaching_usages = sum(
        1 for usage in all_usages if usage.get("products")
    )
    if product_reaching_usages:
        usage_classification = "DIRECTLY_MAPPED_AND_USED"
    elif len(owner_ids) > 1 or len(map_ids) > 1:
        usage_classification = "AMBIGUOUS_OWNERSHIP"
        conflicts.append("Multiple representation maps or type-product owners exist")
    elif owner_ids and all_occurrences:
        usage_classification = "TYPE_OWNED_WITH_OCCURRENCES"
    elif owner_ids:
        usage_classification = "TYPE_OWNED_WITHOUT_OCCURRENCES"
    elif all_usages:
        usage_classification = "UNOWNED_MAP_WITH_USAGE"
    else:
        usage_classification = "UNOWNED_AND_UNUSED"

    candidate_ids = [record["step_id"] for record in candidates]
    equivalent_contexts = set(equivalent["distinct_contexts"])
    occurrence_contexts = {
        context_id
        for occurrence in all_occurrences
        for context_id in occurrence["valid_occurrence_footprint_contexts"]
    }
    usage_footprint_contexts = {
        usage["outer_representation"]["context_of_items"]
        for usage in all_usages
        if usage.get("outer_representation")
        and normal(usage["outer_representation"]["representation_identifier"])
        == TARGET_IDENTIFIER
        and normal(usage["outer_representation"]["representation_type"]) == TARGET_TYPE
        and usage["outer_representation"]["context_of_items"]
    }

    unique_candidate = candidate_ids[0] if len(candidate_ids) == 1 else None
    if len(candidate_ids) != 1:
        conflicts.append(
            f"{len(candidate_ids)} compatible project FootPrint contexts exist"
        )
    if unique_candidate and equivalent_contexts and equivalent_contexts != {unique_candidate}:
        conflicts.append(
            "Equivalent valid FootPrint representations use a conflicting context"
        )
    if unique_candidate and occurrence_contexts - {unique_candidate}:
        conflicts.append(
            "Type occurrence FootPrint representations use another context"
        )
    if unique_candidate and usage_footprint_contexts - {unique_candidate}:
        conflicts.append("Mapped usage reaches a FootPrint representation with another context")

    body_siblings = [
        sibling
        for sibling in all_siblings
        if normal(sibling["representation_identifier"]) == "body"
        and sibling["context_of_items"]
    ]
    candidate_root = (
        indexes.context_records[unique_candidate]["root_context"]
        if unique_candidate else None
    )
    body_roots = {
        sibling["semantic_context"]["root_context"]
        for sibling in body_siblings
        if sibling["semantic_context"]
    }
    hierarchy_supported = bool(
        candidate_root and body_roots and body_roots == {candidate_root}
    )
    if not body_siblings:
        conflicts.append("No valid sibling Body map establishes the context hierarchy")
    elif not hierarchy_supported:
        conflicts.append("Sibling Body map belongs to another context hierarchy")

    ownership_or_usage = bool(owner_ids or product_reaching_usages)
    equivalents_support = bool(equivalent["count"]) and equivalent_contexts == {
        unique_candidate
    }
    if not ownership_or_usage:
        conflicts.append("No valid type ownership or product-reaching map usage exists")
    if not equivalent["count"]:
        conflicts.append("No equivalent valid FootPrint representation exists")

    if usage_classification == "UNOWNED_AND_UNUSED":
        decision = "ORPHANED"
        confidence = "Orphaned"
    elif usage_classification == "AMBIGUOUS_OWNERSHIP" or any(
        "conflict" in conflict.casefold()
        or "another context" in conflict.casefold()
        for conflict in conflicts
    ):
        decision = "AMBIGUOUS"
        confidence = "Ambiguous"
    elif (
        representation_signature(representation) == (TARGET_IDENTIFIER, TARGET_TYPE)
        and len(map_ids) == 1
        and ownership_or_usage
        and unique_candidate
        and equivalents_support
        and hierarchy_supported
        and not conflicts
    ):
        decision = "HIGH_CONFIDENCE_REPAIR"
        confidence = "High"
    else:
        decision = "REPORT_ONLY"
        confidence = "Report only"

    owner_summary = ", ".join(
        f"{record['entity_type']} #{record['step_id']} ({record['name'] or 'unnamed'})"
        for record in all_owner_records
    ) or "No IfcTypeProduct owner"
    evidence_summary = (
        f"Map ownership: {owner_summary}. "
        f"Direct mapped items: {len(all_usages)}; type occurrences: "
        f"{len({item['step_id'] for item in all_occurrences})}. "
        f"Compatible FootPrint context(s): "
        f"{', '.join('#' + str(item) for item in candidate_ids) or 'none'}. "
        f"Equivalent valid FootPrint representations: {equivalent['count']}, using "
        f"{', '.join('#' + str(item) for item in equivalent['distinct_contexts']) or 'none'}. "
        f"Sibling Body hierarchy agreement: {'yes' if hierarchy_supported else 'no'}."
    )
    return {
        "rule_id": RULE_ID,
        "shape_representation_step_id": representation_id,
        "representation_identifier": str(
            value(representation, "RepresentationIdentifier", "") or ""
        ),
        "representation_type": str(value(representation, "RepresentationType", "") or ""),
        "items_count": len(value(representation, "Items", ()) or ()),
        "representation_maps": maps_trace,
        "owner_types": all_owner_records,
        "direct_mapped_usages_count": len(all_usages),
        "direct_mapped_usages": all_usages,
        "type_occurrences_count": len({
            item["step_id"] for item in all_occurrences
        }),
        "type_occurrences": all_occurrences,
        "sibling_representation_maps": all_siblings,
        "equivalent_footprint_representations": equivalent["count"],
        "candidate_contexts": candidates,
        "unique_compatible_context": unique_candidate is not None,
        "selected_context_step_id": unique_candidate if decision == "HIGH_CONFIDENCE_REPAIR" else None,
        "conflicting_evidence": conflicts,
        "usage_classification": usage_classification,
        "repair_decision": decision,
        "repair_confidence": confidence,
        "recommended_action": (
            f"Repair ContextOfItems to #{unique_candidate}"
            if decision == "HIGH_CONFIDENCE_REPAIR"
            else "Leave unchanged"
        ),
        "evidence_summary": evidence_summary,
        "shape_inbound_references": indexes.reverse_references.get(
            representation_id, []
        ),
        "shape_outbound_references": indexes.outbound_references.get(
            representation_id, []
        ),
        "schema_validity_impact": "Invalid: existing IfcShapeRepresentation has no context",
        "rendering_impact": (
            "Low for uninstantiated type-level geometry; potentially higher when mapped"
        ),
        "downstream_processing_impact": (
            "May affect strict validation, transformations, geometry extraction, and future type reuse"
        ),
        "practical_repair_priority": (
            "Recommended schema cleanup" if decision == "HIGH_CONFIDENCE_REPAIR"
            else "Review before changing"
        ),
    }


def summary_groups(cases: list[dict[str, Any]]) -> dict[str, Any]:
    def count_by(values: Iterable[str]) -> dict[str, int]:
        return dict(sorted(Counter(values).items()))

    return {
        "owner_type_product_class": count_by(
            owner["entity_type"]
            for case in cases
            for owner in case["owner_types"]
        ),
        "owner_type_product_name": count_by(
            owner["name"] or "(unnamed)"
            for case in cases
            for owner in case["owner_types"]
        ),
        "usage_classification": count_by(
            case["usage_classification"] for case in cases
        ),
        "candidate_context": count_by(
            (
                f"#{case['selected_context_step_id']}"
                if case["selected_context_step_id"]
                else ", ".join(
                    f"#{context['step_id']}" for context in case["candidate_contexts"]
                ) or "None"
            )
            for case in cases
        ),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )


def html_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(
            f"<td>{html.escape(str(cell))}</td>" for cell in row
        ) + "</tr>"
        for row in rows
    )
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def write_html(path: Path, analysis: dict[str, Any]) -> None:
    cases = analysis["cases"]
    summary = analysis["summary"]
    context_rows = [
        [
            f"#{record['step_id']}",
            record["entity_type"],
            record["context_identifier"],
            record["context_type"],
            record["coordinate_space_dimension"],
            record["target_view"] or "—",
            f"#{record['parent_context']}" if record["parent_context"] else "—",
            "Yes" if record["connected_to_project"] else "No",
        ]
        for record in analysis["context_semantic_table"]
    ]
    case_rows = [
        [
            f"#{case['shape_representation_step_id']}",
            ", ".join(
                f"#{item['representation_map_step_id']}"
                for item in case["representation_maps"]
            ),
            ", ".join(
                f"{owner['entity_type']} #{owner['step_id']}"
                for owner in case["owner_types"]
            ) or "—",
            case["direct_mapped_usages_count"],
            case["type_occurrences_count"],
            case["equivalent_footprint_representations"],
            ", ".join(f"#{item['step_id']}" for item in case["candidate_contexts"]),
            case["usage_classification"],
            case["repair_confidence"],
            case["recommended_action"],
        ]
        for case in cases
    ]
    ownership_sections = "".join(
        f"""
        <details>
          <summary>Shape #{case['shape_representation_step_id']} — {html.escape(case['repair_decision'])}</summary>
          <p>{html.escape(case['evidence_summary'])}</p>
          <p><b>Conflicts:</b> {html.escape('; '.join(case['conflicting_evidence']) or 'None')}</p>
          <pre>{html.escape(json.dumps({
              'representation_maps': case['representation_maps'],
              'owner_types': case['owner_types'],
              'sibling_representation_maps': case['sibling_representation_maps'],
              'shape_inbound_references': case['shape_inbound_references'],
              'shape_outbound_references': case['shape_outbound_references'],
          }, indent=2))}</pre>
        </details>
        """
        for case in cases
    )
    usage_sections = "".join(
        f"""
        <details>
          <summary>Shape #{case['shape_representation_step_id']} — mapped usage and occurrences</summary>
          <pre>{html.escape(json.dumps({
              'direct_mapped_usages': case['direct_mapped_usages'],
              'type_occurrences': case['type_occurrences'],
          }, indent=2))}</pre>
        </details>
        """
        for case in cases
    )
    verification = analysis.get("verification")
    verification_html = (
        f"<pre>{html.escape(json.dumps(verification, indent=2))}</pre>"
        if verification
        else "<p>Patch verification has not yet run.</p>"
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Final 16 missing FootPrint contexts</title>
<style>
body{{font:14px/1.5 Segoe UI,Arial,sans-serif;margin:0;background:#f4f7fb;color:#172033}}
main{{max-width:1500px;margin:auto;padding:28px}} h1,h2{{margin-top:0}}
nav{{position:sticky;top:0;background:#fff;padding:12px 28px;border-bottom:1px solid #dbe3ef;z-index:2}}
nav a{{margin-right:18px;color:#165dcc;text-decoration:none}}
.card{{background:#fff;border:1px solid #dbe3ef;border-radius:10px;padding:20px;margin:18px 0}}
.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
.metric{{background:#eef4ff;border-radius:8px;padding:14px}}.metric b{{font-size:24px;display:block}}
.table-wrap{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:1100px}}
th,td{{padding:9px 10px;border-bottom:1px solid #e0e6ef;text-align:left;vertical-align:top}}
th{{background:#f2f6fc;position:sticky;top:0}}details{{border-top:1px solid #e0e6ef;padding:10px 0}}
summary{{font-weight:600;cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;padding:12px}}
.ok{{color:#137a36}}.warn{{color:#9a5b00}}
</style></head><body>
<nav><a href="#overview">Overview</a><a href="#cases">All 16 Cases</a>
<a href="#ownership">Ownership Chains</a><a href="#usage">Mapped Usage</a>
<a href="#occurrences">Type Occurrences</a><a href="#contexts">Context Candidates</a>
<a href="#decision">Repair Decision</a><a href="#verification">Verification</a></nav>
<main>
<section id="overview" class="card"><h1>Final 16 Missing FootPrint Contexts</h1>
<p><b>Source:</b> {html.escape(analysis['input']['path'])}</p>
<p><b>SHA-256:</b> {html.escape(analysis['input']['sha256'])}</p>
<div class="metrics">
<div class="metric"><b>{summary['total_targets']}</b>Total targets</div>
<div class="metric"><b>{summary['high_confidence_repairable']}</b>High confidence</div>
<div class="metric"><b>{summary['report_only']}</b>Report only</div>
<div class="metric"><b>{summary['ambiguous']}</b>Ambiguous</div>
<div class="metric"><b>{summary['orphaned']}</b>Orphaned</div>
</div></section>
<section id="cases" class="card"><h2>All 16 Cases</h2>
{html_table(['Shape ID','Map ID','Owner type','Mapped usages','Type occurrences',
'Equivalent FootPrint reps','Candidate contexts','Usage classification',
'Confidence','Action'], case_rows)}</section>
<section id="ownership" class="card"><h2>Ownership Chains</h2>{ownership_sections}</section>
<section id="usage" class="card"><h2>Mapped Usage</h2>{usage_sections}</section>
<section id="occurrences" class="card"><h2>Type Occurrences</h2>
<p>Occurrence records are included per case above, including whether occurrence geometry reaches the target map.</p>
</section>
<section id="contexts" class="card"><h2>Context Candidates</h2>
{html_table(['STEP ID','Entity type','Identifier','Context type','Dimension','Target view',
'Parent','Project connected'], context_rows)}
<p>IfcGeometricRepresentationSubContext inherits coordinate-space dimension from its parent;
a Revit PLAN_VIEW FootPrint can therefore report inherited dimension 3 while its Curve2D items remain 2D.</p>
</section>
<section id="decision" class="card"><h2>Repair Decision</h2>
<pre>{html.escape(json.dumps(summary['groups'], indent=2))}</pre>
<p>Schema status is invalid for every target because an existing IfcShapeRepresentation has an unset ContextOfItems.
Rendering impact may be low for type-level or uninstantiated maps, but strict validation and future type geometry reuse remain affected.</p>
</section>
<section id="verification" class="card"><h2>Verification</h2>{verification_html}</section>
</main></body></html>"""
    path.write_text(document, encoding="utf-8", newline="\n")


def line_by_line_change_audit(
    source: Path,
    output: Path,
    replacements: dict[int, int],
) -> dict[str, Any]:
    differing_lines = 0
    changed_step_ids: set[int] = set()
    unexpected_lines: list[int] = []
    line_number = 0
    with source.open("rb") as before, output.open("rb") as after:
        while True:
            source_line = before.readline()
            output_line = after.readline()
            if not source_line and not output_line:
                break
            line_number += 1
            if source_line == output_line:
                continue
            differing_lines += 1
            match = SHAPE_LINE.match(source_line)
            if not match:
                unexpected_lines.append(line_number)
                continue
            entity_id = int(match.group(1))
            if entity_id not in replacements or match.group(2) != b"$":
                unexpected_lines.append(line_number)
                continue
            expected_line = (
                source_line[:match.start(2)]
                + f"#{replacements[entity_id]}".encode("ascii")
                + source_line[match.end(2):]
            )
            if output_line != expected_line:
                unexpected_lines.append(line_number)
                continue
            changed_step_ids.add(entity_id)
    expected_ids = set(replacements)
    return {
        "line_count": line_number,
        "differing_lines": differing_lines,
        "expected_modified_step_records": len(expected_ids),
        "actual_modified_step_records": len(changed_step_ids),
        "changed_step_ids": sorted(changed_step_ids),
        "missing_expected_step_ids": sorted(expected_ids - changed_step_ids),
        "unexpected_modified_step_ids": sorted(changed_step_ids - expected_ids),
        "unexpected_line_numbers": unexpected_lines[:100],
        "passed": (
            changed_step_ids == expected_ids
            and not unexpected_lines
            and differing_lines == len(expected_ids)
        ),
    }


def unchanged_relevant_record_audit(
    source: Path,
    output: Path,
    protected_ids: set[int],
) -> dict[str, Any]:
    before_hashes: dict[int, str] = {}
    after_hashes: dict[int, str] = {}
    for path, destination in ((source, before_hashes), (output, after_hashes)):
        with path.open("rb") as stream:
            for line in stream:
                match = ENTITY_LINE.match(line)
                if not match:
                    continue
                entity_id = int(match.group(1))
                if entity_id in protected_ids:
                    destination[entity_id] = hashlib.sha256(line).hexdigest()
    missing = sorted(protected_ids - set(before_hashes) | protected_ids - set(after_hashes))
    changed = sorted(
        entity_id
        for entity_id in protected_ids & set(before_hashes) & set(after_hashes)
        if before_hashes[entity_id] != after_hashes[entity_id]
    )
    return {
        "protected_step_ids": sorted(protected_ids),
        "missing_step_ids": missing,
        "changed_step_ids": changed,
        "passed": not missing and not changed,
    }


def run(source: Path, output_dir: Path) -> int:
    started = time.perf_counter()
    source = source.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis_json = output_dir / "final_16_analysis.json"
    analysis_html = output_dir / "final_16_analysis.html"
    repaired_ifc = output_dir / "final_16_repaired.ifc"
    verification_json = output_dir / "final_16_patch_verification.json"
    temporary_ifc = output_dir / ".final_16_repaired.tmp.ifc"

    if not source.is_file():
        raise FileNotFoundError(source)
    if source == repaired_ifc:
        raise RuntimeError("Source and output IFC paths must differ")

    source_stat = source.stat()
    source_hash = sha256(source)
    fingerprint_before = source_fingerprint(source)
    print(f"Opening {source.name} ({source_stat.st_size:,} bytes)", flush=True)
    parse_started = time.perf_counter()
    model = ifcopenshell.open(str(source))
    parse_seconds = time.perf_counter() - parse_started
    print(f"Parsed IFC in {parse_seconds:.2f}s; building indexes", flush=True)
    index_started = time.perf_counter()
    indexes = build_indexes(model)
    index_seconds = time.perf_counter() - index_started
    targets = target_representations(indexes)
    print(f"Confirmed {len(targets)} target representation(s)", flush=True)
    if len(targets) != EXPECTED_TARGETS:
        raise RuntimeError(
            f"Target-count discrepancy: expected {EXPECTED_TARGETS}, found {len(targets)}. "
            "No analysis or repaired IFC was created."
        )

    target_ids = {step_id(item) for item in targets}
    target_map_ids = {
        map_id
        for target_id in target_ids
        for map_id in indexes.shape_representation_to_maps.get(target_id, ())
    }
    owner_type_ids = {
        type_id
        for map_id in target_map_ids
        for type_id, _position in indexes.representation_map_to_type_products.get(
            map_id, ()
        )
    }
    relevant_entities = {
        **{item_id: indexes.shape_representations[item_id] for item_id in target_ids},
        **{item_id: indexes.maps[item_id] for item_id in target_map_ids},
        **{item_id: indexes.type_products[item_id] for item_id in owner_type_ids},
    }
    populate_reference_indexes(model, relevant_entities, indexes)

    all_context_records = sorted(
        indexes.context_records.values(), key=lambda item: item["step_id"]
    )
    candidates = [
        record for record in all_context_records
        if compatible_footprint_context(record)
    ]
    equivalent = equivalent_footprints(indexes)
    cases = [
        analyse_case(target, indexes, candidates, equivalent)
        for target in targets
    ]
    decision_counts = Counter(case["repair_decision"] for case in cases)
    summary = {
        "total_targets": len(cases),
        "high_confidence_repairable": decision_counts["HIGH_CONFIDENCE_REPAIR"],
        "report_only": decision_counts["REPORT_ONLY"],
        "ambiguous": decision_counts["AMBIGUOUS"],
        "orphaned": decision_counts["ORPHANED"],
        "groups": summary_groups(cases),
    }
    analysis: dict[str, Any] = {
        "analysis_version": "1.0",
        "rule_id": RULE_ID,
        "created_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "input": {
            "path": str(source),
            "size_bytes": source_stat.st_size,
            "modified_ns": source_stat.st_mtime_ns,
            "sha256": source_hash,
            "ifc_schema": str(getattr(model, "schema", "")),
            "ifcopenshell_version": ifcopenshell.version,
        },
        "scope": {
            "entity_type": "IfcShapeRepresentation",
            "context_of_items": "$",
            "representation_identifier": "FootPrint",
            "representation_type": "Curve2D",
            "owner_structure": "IfcRepresentationMap.MappedRepresentation",
            "expected_count": EXPECTED_TARGETS,
            "confirmed_count": len(cases),
        },
        "timings_seconds": {
            "parse_ifc": parse_seconds,
            "build_indexes": index_seconds,
        },
        "context_semantic_table": all_context_records,
        "compatible_contexts": candidates,
        "equivalent_valid_footprints": equivalent,
        "summary": summary,
        "cases": cases,
        "verification": None,
        "production_rule_recommendation": {
            "recommended": summary["high_confidence_repairable"] > 0,
            "rule_id": RULE_ID,
            "conditions": [
                "MappedRepresentation.ContextOfItems is unset",
                "RepresentationIdentifier is FootPrint",
                "RepresentationType is Curve2D",
                "Exactly one compatible project-connected semantic FootPrint context exists",
                "Valid IfcTypeProduct ownership or product-reaching mapped usage is proven",
                "Equivalent valid FootPrint representations support the candidate",
                "Sibling Body map belongs to the same root context hierarchy",
                "No conflicting type occurrence or map usage context exists",
            ],
            "no_occurrence_policy": (
                "Valid IfcTypeProduct ownership can establish meaningful type-level geometry "
                "even without current occurrences; practical impact is low but high-confidence "
                "schema cleanup remains allowed."
            ),
        },
    }

    # Persist the complete analysis before creating any repaired IFC.
    write_json(analysis_json, analysis)
    write_html(analysis_html, analysis)
    print(
        f"Analysis complete: {summary['high_confidence_repairable']} high-confidence, "
        f"{summary['report_only']} report-only, {summary['ambiguous']} ambiguous, "
        f"{summary['orphaned']} orphaned",
        flush=True,
    )

    replacements = {
        case["shape_representation_step_id"]: case["selected_context_step_id"]
        for case in cases
        if case["repair_decision"] == "HIGH_CONFIDENCE_REPAIR"
        and case["selected_context_step_id"]
    }
    if not replacements:
        verification = {
            "patch_created": False,
            "reason": "No cases qualified as HIGH_CONFIDENCE_REPAIR",
            "source_unchanged": source_fingerprint(source) == fingerprint_before,
        }
        analysis["verification"] = verification
        write_json(analysis_json, analysis)
        write_html(analysis_html, analysis)
        write_json(verification_json, verification)
        return 0

    if temporary_ifc.exists():
        temporary_ifc.unlink()
    patch_started = time.perf_counter()
    plan = build_patch_plan(source, replacements)
    validate_patch_plan(plan)
    write_result = apply_patch_plan(plan, temporary_ifc)
    envelope = verify_step_envelope(temporary_ifc, plan.expected_output_size)
    target_verification = verify_targeted_output(
        temporary_ifc,
        replacements,
        source=source,
        plan=plan,
        write_result=write_result,
        envelope=envelope,
    )
    line_audit = line_by_line_change_audit(source, temporary_ifc, replacements)

    protected_ids = set(target_map_ids) | set(owner_type_ids)
    protected_ids.update(
        item_id
        for map_id in target_map_ids
        for item_id in indexes.representation_map_to_mapped_items.get(map_id, ())
    )
    relationship_audit = unchanged_relevant_record_audit(
        source, temporary_ifc, protected_ids
    )
    approved_context_validation = [
        {
            "shape_representation_step_id": entity_id,
            "context_step_id": context_id,
            "context_reference_exists": context_id in indexes.contexts,
            "context_entity_type": entity_type(indexes.contexts.get(context_id)),
            "is_geometric_context": entity_type(indexes.contexts.get(context_id)) in {
                "IfcGeometricRepresentationContext",
                "IfcGeometricRepresentationSubContext",
            },
            "compatible_with_footprint_curve2d": (
                context_id in indexes.context_records
                and compatible_footprint_context(indexes.context_records[context_id])
            ),
        }
        for entity_id, context_id in sorted(replacements.items())
    ]
    contexts_valid = all(
        item["context_reference_exists"]
        and item["is_geometric_context"]
        and item["compatible_with_footprint_curve2d"]
        for item in approved_context_validation
    )
    source_unchanged_before_install = source_fingerprint(source) == fingerprint_before
    all_passed = (
        target_verification.passed
        and line_audit["passed"]
        and relationship_audit["passed"]
        and contexts_valid
        and source_unchanged_before_install
    )
    if not all_passed:
        verification = {
            "patch_created": False,
            "temporary_output_removed": False,
            "target_verification": asdict(target_verification),
            "line_by_line_change_audit": line_audit,
            "relationship_integrity": relationship_audit,
            "approved_context_validation": approved_context_validation,
            "source_unchanged": source_unchanged_before_install,
            "passed": False,
        }
        try:
            temporary_ifc.unlink()
            verification["temporary_output_removed"] = True
        finally:
            analysis["verification"] = verification
            write_json(analysis_json, analysis)
            write_html(analysis_html, analysis)
            write_json(verification_json, verification)
        raise RuntimeError("Patch verification failed; repaired IFC was not installed")

    os.replace(temporary_ifc, repaired_ifc)
    output_hash = sha256(repaired_ifc)
    source_unchanged_after_install = (
        source_fingerprint(source) == fingerprint_before and sha256(source) == source_hash
    )
    verification = {
        "patch_created": True,
        "output_path": str(repaired_ifc),
        "output_size_bytes": repaired_ifc.stat().st_size,
        "output_sha256": output_hash,
        "approved_targets": len(replacements),
        "approved_replacements": {
            str(entity_id): context_id
            for entity_id, context_id in sorted(replacements.items())
        },
        "approved_context_validation": approved_context_validation,
        "target_verification": asdict(target_verification),
        "line_by_line_change_audit": line_audit,
        "relationship_integrity": relationship_audit,
        "representation_map_relationships_unchanged": relationship_audit["passed"],
        "type_product_relationships_unchanged": relationship_audit["passed"],
        "mapped_item_links_unchanged": relationship_audit["passed"],
        "non_approved_targets_unchanged": True,
        "source_unchanged": source_unchanged_after_install,
        "write_telemetry": asdict(write_result),
        "patch_and_verification_seconds": time.perf_counter() - patch_started,
        "passed": all_passed and source_unchanged_after_install,
    }
    analysis["verification"] = verification
    analysis["timings_seconds"]["total"] = time.perf_counter() - started
    write_json(analysis_json, analysis)
    write_html(analysis_html, analysis)
    write_json(verification_json, verification)
    print(
        f"Patched and verified {len(replacements)} target(s); output: {repaired_ifc}",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and conditionally repair the final 16 mapped FootPrint contexts."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        return run(arguments.source, arguments.output_dir)
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
