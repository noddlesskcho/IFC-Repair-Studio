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
    timings: dict[str, float] | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[list[Diagnosis], SemanticIndex]:
    mark = time.perf_counter()
    slabs = list(model.by_type("IfcSlab"))
    if timings is not None:
        timings["collect_target_slabs"] = time.perf_counter() - mark
    if progress:
        progress("collect_target_slabs", len(slabs), len(slabs))
    mark = time.perf_counter()
    representations: list[Any] = []
    seen: set[int] = set()
    for position, slab in enumerate(slabs, 1):
        if cancelled and cancelled():
            from .errors import CancelledError
            raise CancelledError("Scan cancelled while collecting slab representations")
        owner = attr(slab, "Representation")
        for rep in attr(owner, "Representations", ()) or ():
            rid = entity_id(rep)
            if rid and rid not in seen and entity_type(rep) == "IfcShapeRepresentation":
                representations.append(rep)
                seen.add(rid)
        if progress and (position % 100 == 0 or position == len(slabs)):
            progress("collect_shape_representations", position, len(slabs))
    if timings is not None:
        timings["collect_shape_representations"] = time.perf_counter() - mark
    mark = time.perf_counter()
    index = SemanticIndex.build(model, representations, products=slabs)
    if timings is not None:
        timings["context_index"] = time.perf_counter() - mark
    mark = time.perf_counter()
    diagnoses: list[Diagnosis] = []
    resolution_cache: dict[tuple[str, str, str, str], Any] = {}
    for position, rep in enumerate(representations, 1):
        if cancelled and cancelled():
            from .errors import CancelledError
            raise CancelledError("Scan cancelled while resolving contexts")
        context = attr(rep, "ContextOfItems")
        context_id = entity_id(context)
        invalid = context_id is None or context_id not in index.contexts
        if not invalid and not include_valid:
            continue
        product = index.product_for(rep)
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
        else:
            diagnosis.status = Status.VALID
            diagnosis.confidence = 1.0
        diagnoses.append(diagnosis)
        if progress and (position % 100 == 0 or position == len(representations)):
            progress("context_resolution", position, len(representations))
    index.total_shape_representations = len(representations)
    index.total_products = len(slabs)
    if timings is not None:
        timings["context_resolution"] = time.perf_counter() - mark
    return diagnoses, index
