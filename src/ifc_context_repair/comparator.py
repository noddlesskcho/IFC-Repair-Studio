from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .context_index import SemanticIndex, attr, entity_type
from .detector import diagnose_model
from .parser import open_model


def _patterns(model: Any) -> Counter[tuple[str, str, str, str, str, str]]:
    index = SemanticIndex.build(model)
    result: Counter[tuple[str, str, str, str, str, str]] = Counter()
    for rep in model.by_type("IfcShapeRepresentation"):
        product = index.product_for(rep)
        context = attr(rep, "ContextOfItems")
        items = attr(rep, "Items", ()) or ()
        result[(
            entity_type(product) or "",
            str(attr(rep, "RepresentationIdentifier", "") or ""),
            str(attr(rep, "RepresentationType", "") or ""),
            entity_type(items[0]) if items else "",
            str(attr(context, "ContextIdentifier", "") or ""),
            str(attr(context, "TargetView", "") or ""),
        )] += 1
    return result


def compare_files(clean: Path, faulty: Path) -> dict[str, object]:
    clean_model = open_model(clean)
    faulty_model = open_model(faulty)
    faulty_diagnoses, _ = diagnose_model(faulty_model)
    clean_patterns = _patterns(clean_model)
    faulty_patterns = _patterns(faulty_model)
    return {
        "clean_file": str(clean.resolve()),
        "faulty_file": str(faulty.resolve()),
        "schemas": {"clean": str(clean_model.schema), "faulty": str(faulty_model.schema)},
        "affected_in_faulty": [d.to_dict() for d in faulty_diagnoses],
        "patterns_only_in_clean": [
            {"signature": list(key), "count": count - faulty_patterns.get(key, 0)}
            for key, count in clean_patterns.items() if count > faulty_patterns.get(key, 0)
        ],
        "patterns_only_in_faulty": [
            {"signature": list(key), "count": count - clean_patterns.get(key, 0)}
            for key, count in faulty_patterns.items() if count > clean_patterns.get(key, 0)
        ],
        "note": "Semantic signatures are compared; STEP IDs are intentionally excluded.",
    }
