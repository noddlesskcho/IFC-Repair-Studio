from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .context_index import SemanticIndex, attr, entity_id, entity_type
from .hashing import sha256_file
from .parser import open_model
from .prescan import scan_step
from .validator import validate_schema


def analyse_clean_baselines(paths: list[Path]) -> dict[str, Any]:
    """Describe known-clean files without deriving rules from STEP IDs."""
    files: list[dict[str, Any]] = []
    aggregate_patterns: Counter[tuple[str, str, str, str, str, str]] = Counter()
    for path in paths:
        source = path.resolve()
        model = open_model(source)
        index = SemanticIndex.build(model)
        candidates = scan_step(source)
        issues = validate_schema(model)
        patterns: Counter[tuple[str, str, str, str, str, str]] = Counter()
        representations: list[dict[str, Any]] = []
        for rep in model.by_type("IfcShapeRepresentation"):
            product = index.product_for(rep)
            context = attr(rep, "ContextOfItems")
            items = attr(rep, "Items", ()) or ()
            item_types = ",".join(sorted(entity_type(item) or "" for item in items))
            signature = (
                entity_type(product) or "Unresolved owner",
                str(attr(rep, "RepresentationIdentifier", "") or ""),
                str(attr(rep, "RepresentationType", "") or ""),
                item_types,
                str(attr(context, "ContextIdentifier", "") or ""),
                str(attr(context, "TargetView", "") or ""),
            )
            patterns[signature] += 1
            aggregate_patterns[signature] += 1
            representations.append({
                "step_id_local_only": entity_id(rep),
                "product_class": entity_type(product),
                "product_global_id": attr(product, "GlobalId"),
                "representation_identifier": attr(rep, "RepresentationIdentifier"),
                "representation_type": attr(rep, "RepresentationType"),
                "item_types": [entity_type(item) for item in items],
                "context_step_id_local_only": entity_id(context),
                "context_identifier": attr(context, "ContextIdentifier"),
                "context_type": attr(context, "ContextType"),
                "target_view": str(attr(context, "TargetView")) if attr(context, "TargetView") else None,
            })
        files.append({
            "path": str(source),
            "filename": source.name,
            "sha256": sha256_file(source),
            "schema": str(model.schema),
            "originating_system": str(model.header.file_name.originating_system),
            "preprocessor_version": str(model.header.file_name.preprocessor_version),
            "project_count": len(model.by_type("IfcProject")),
            "slab_count": len(model.by_type("IfcSlab")),
            "shape_representation_count": len(representations),
            "missing_context_candidates": len(candidates),
            "validation_issue_count": len(issues),
            "is_clean_baseline": not candidates and not issues,
            "patterns": [{"signature": list(key), "count": count}
                         for key, count in sorted(patterns.items())],
            "representations": representations,
        })
    return {
        "purpose": "Known-clean semantic baseline; STEP IDs are local and non-transferable",
        "file_count": len(files),
        "all_files_clean": all(item["is_clean_baseline"] for item in files),
        "files": files,
        "aggregate_patterns": [
            {"signature": list(key), "count": count}
            for key, count in sorted(aggregate_patterns.items())
        ],
    }
