from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .context_index import SemanticIndex, attr, entity_id, entity_type
from .models import Diagnosis, Status
from .resolver import resolve_context


def diagnose_model(
    model: Any,
    include_valid: bool = False,
    *,
    product_types: tuple[str, ...] = ("IfcSlab",),
    allowed_signatures: dict[str, frozenset[tuple[str, str]]] | None = None,
    timings: dict[str, float] | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[list[Diagnosis], SemanticIndex]:
    mark = time.perf_counter()
    products: list[Any] = []
    scope_by_product_id: dict[int, str] = {}
    seen_products: set[int] = set()
    for product_type in product_types:
        for product in model.by_type(product_type):
            pid = entity_id(product)
            if not pid or pid in seen_products:
                continue
            products.append(product)
            seen_products.add(pid)
            # Keep the concrete class even when collecting through IfcProduct.
            scope_by_product_id[pid] = entity_type(product) or product_type
    if timings is not None:
        timings["collect_target_elements"] = time.perf_counter() - mark
    if progress:
        progress("collect_target_elements", len(products), len(products))
    mark = time.perf_counter()
    representations: list[Any] = []
    seen: set[int] = set()
    representations_by_scope: dict[str, int] = {
        product_type: 0 for product_type in product_types
    }
    for position, product in enumerate(products, 1):
        if cancelled and cancelled():
            from .errors import CancelledError
            raise CancelledError("Scan cancelled while collecting element representations")
        owner = attr(product, "Representation")
        scope = scope_by_product_id.get(entity_id(product) or -1, "")
        for rep in attr(owner, "Representations", ()) or ():
            rid = entity_id(rep)
            if rid and rid not in seen and entity_type(rep) == "IfcShapeRepresentation":
                representations.append(rep)
                seen.add(rid)
                representations_by_scope[scope] = representations_by_scope.get(scope, 0) + 1
        if progress and (position % 100 == 0 or position == len(products)):
            progress("collect_shape_representations", position, len(products))
    if timings is not None:
        timings["collect_shape_representations"] = time.perf_counter() - mark
    mark = time.perf_counter()
    if progress:
        progress("context_index", 0, 1)
    index = SemanticIndex.build(model, representations, products=products)
    index.product_scope.update(scope_by_product_id)
    index.products_by_scope.update(scope_by_product_id.values())
    index.representations_by_scope.update(representations_by_scope)
    if timings is not None:
        timings["context_index"] = time.perf_counter() - mark
    if progress:
        progress("context_index", 1, 1)
    mark = time.perf_counter()
    diagnoses: list[Diagnosis] = []
    resolution_cache: dict[tuple[str, str, str, str], Any] = {}
    hosted_opening_ids: set[int] = set()
    if "IfcOpeningElement" in scope_by_product_id.values():
        relationships = list(model.by_type("IfcRelVoidsElement"))
        if progress:
            progress("opening_relationships", 0, len(relationships))
        for position, relationship in enumerate(relationships, 1):
            if cancelled and cancelled():
                from .errors import CancelledError
                raise CancelledError(
                    "Scan cancelled while checking opening relationships"
                )
            opening_id = entity_id(attr(relationship, "RelatedOpeningElement"))
            if opening_id:
                hosted_opening_ids.add(opening_id)
            if progress and (
                position % 100 == 0 or position == len(relationships)
            ):
                progress("opening_relationships", position, len(relationships))
    if timings is not None:
        timings["opening_relationships"] = time.perf_counter() - mark
    mark = time.perf_counter()
    for position, rep in enumerate(representations, 1):
        if cancelled and cancelled():
            from .errors import CancelledError
            raise CancelledError("Scan cancelled while resolving contexts")
        context = attr(rep, "ContextOfItems")
        context_id = entity_id(context)
        invalid = context_id is None or context_id not in index.contexts
        if progress and (position % 100 == 0 or position == len(representations)):
            progress("context_resolution", position, len(representations))
        if not invalid and not include_valid:
            continue
        product = index.product_for(rep)
        scope = scope_by_product_id.get(entity_id(product) or -1, "")
        signature_pair = (
            str(attr(rep, "RepresentationIdentifier", "") or "").casefold(),
            str(attr(rep, "RepresentationType", "") or "").casefold(),
        )
        if invalid and allowed_signatures is not None:
            allowed = allowed_signatures.get(
                scope, allowed_signatures.get("*", frozenset())
            )
            if signature_pair not in allowed:
                continue
        owner = index.owner_for(rep)
        items = list(attr(rep, "Items", ()) or ())
        diagnosis = Diagnosis(
            representation_step_id=entity_id(rep) or 0,
            representation_identifier=attr(rep, "RepresentationIdentifier"),
            representation_type=attr(rep, "RepresentationType"),
            item_count=len(items),
            item_classes=[entity_type(item) or "Unknown" for item in items],
            current_context_step_id=context_id,
            product_class=entity_type(product),
            product_step_id=entity_id(product),
            product_global_id=attr(product, "GlobalId"),
            product_name=attr(product, "Name"),
            product_tag=attr(product, "Tag"),
            owner_step_id=entity_id(owner),
        )
        if invalid:
            signature = index.signature(rep, product)
            result = resolution_cache.get(signature)
            if result is None:
                result = resolve_context(rep, index)
                resolution_cache[signature] = result
            diagnosis.status = result.status
            diagnosis.confidence = result.confidence
            diagnosis.evidence = result.evidence
            diagnosis.conflicts = result.conflicts
            diagnosis.decision_trace = result.decision_trace
            diagnosis.candidates = result.candidates
            if result.context:
                diagnosis.proposed_context = index.context_info[entity_id(result.context)]
            if scope == "IfcOpeningElement" and (
                diagnosis.product_step_id not in hosted_opening_ids
            ):
                diagnosis.status = Status.NOT_REPAIRABLE
                diagnosis.proposed_context = None
                diagnosis.conflicts.append(
                    "Opening is not connected to a host through IfcRelVoidsElement"
                )
        else:
            diagnosis.status = Status.VALID
            diagnosis.confidence = 1.0
        diagnoses.append(diagnosis)
    index.total_shape_representations = len(representations)
    index.total_products = len(products)
    if timings is not None:
        timings["context_resolution"] = time.perf_counter() - mark
    return diagnoses, index
