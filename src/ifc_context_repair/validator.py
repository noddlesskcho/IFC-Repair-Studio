from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .context_index import attr, entity_id
from .hashing import sha256_file
from .models import Diagnosis, FileSnapshot, ValidationIssue


def validate_schema(model: Any, express_rules: bool = True) -> list[ValidationIssue]:
    try:
        import ifcopenshell.validate as validate

        logger = validate.json_logger()
        try:
            validate.validate(model, logger, express_rules=express_rules)
        except TypeError:
            validate.validate(model, logger)
        statements = getattr(logger, "statements", [])
        issues = []
        for entry in statements:
            if isinstance(entry, str):
                try:
                    entry = json.loads(entry)
                except json.JSONDecodeError:
                    entry = {"message": entry}
            instance = entry.get("instance") if isinstance(entry, dict) else None
            issues.append(ValidationIssue(
                level=str(entry.get("level", "error")),
                message=str(entry.get("message", entry)),
                entity_step_id=entity_id(instance),
                attribute=str(entry.get("attribute")) if entry.get("attribute") else None,
            ))
        return issues
    except Exception as exc:
        return [ValidationIssue("error", f"IfcOpenShell validation failed: {exc}")]


def validate_targeted(model: Any, repaired: list[Diagnosis]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    context_ids = {
        entity_id(c) for c in model.by_type("IfcGeometricRepresentationContext")
    }
    for diagnosis in repaired:
        try:
            rep = model.by_id(diagnosis.representation_step_id)
        except Exception:
            rep = None
        if rep is None:
            issues.append(ValidationIssue(
                "error", "Repaired representation no longer exists",
                diagnosis.representation_step_id,
            ))
            continue
        cid = entity_id(attr(rep, "ContextOfItems"))
        if cid is None:
            issues.append(ValidationIssue(
                "error", "ContextOfItems remains unset", diagnosis.representation_step_id,
                "ContextOfItems",
            ))
        elif cid not in context_ids:
            issues.append(ValidationIssue(
                "error", "ContextOfItems does not reference a model context",
                diagnosis.representation_step_id, "ContextOfItems",
            ))
    return issues


def snapshot(model: Any, path: Path, target_ids: set[int] | None = None) -> FileSnapshot:
    class_counts = Counter()
    globals_by_class: dict[str, list[str]] = {}
    item_count = 0
    assignments: dict[str, int | None] = {}
    for entity in model:
        kind = str(entity.is_a())
        class_counts[kind] += 1
        guid = attr(entity, "GlobalId")
        if guid:
            globals_by_class.setdefault(kind, []).append(str(guid))
    for rep in model.by_type("IfcShapeRepresentation"):
        rid = entity_id(rep)
        item_count += len(attr(rep, "Items", ()) or ())
        if not target_ids or rid in target_ids:
            assignments[str(rid)] = entity_id(attr(rep, "ContextOfItems"))
    return FileSnapshot(
        schema=str(getattr(model, "schema", None)),
        counts=dict(sorted(class_counts.items())),
        global_ids={k: sorted(v) for k, v in sorted(globals_by_class.items())},
        representation_items=item_count,
        target_assignments=assignments,
        size=path.stat().st_size,
        sha256=sha256_file(path),
    )


def semantic_change_issues(before: FileSnapshot, after: FileSnapshot) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if before.schema != after.schema:
        issues.append(ValidationIssue("error", "IFC schema changed during repair"))
    if before.counts != after.counts:
        issues.append(ValidationIssue("error", "Entity counts changed during repair"))
    if before.global_ids != after.global_ids:
        issues.append(ValidationIssue("error", "GlobalId population changed during repair"))
    if before.representation_items != after.representation_items:
        issues.append(ValidationIssue("error", "Representation item count changed during repair"))
    return issues


def classify_issues(before: list[ValidationIssue], after: list[ValidationIssue]) -> tuple[
    list[ValidationIssue], list[ValidationIssue], list[ValidationIssue]
]:
    def key(issue: ValidationIssue) -> tuple[str, str, int | None, str | None]:
        return (issue.level.casefold(), issue.message, issue.entity_step_id, issue.attribute)

    before_keys = {key(issue) for issue in before}
    after_keys = {key(issue) for issue in after}
    new = [issue for issue in after if key(issue) not in before_keys]
    resolved = [issue for issue in before if key(issue) not in after_keys]
    unchanged = [issue for issue in after if key(issue) in before_keys]
    return new, resolved, unchanged
