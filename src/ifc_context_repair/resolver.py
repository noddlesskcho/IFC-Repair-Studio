from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .context_index import SemanticIndex, attr, entity_id
from .models import ContextInfo, Status
from .reference_profiles import SUPPLIED_CLEAN_PATTERNS


@dataclass(slots=True)
class Resolution:
    status: Status
    context: Any | None
    confidence: float
    evidence: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    candidates: list[ContextInfo] = field(default_factory=list)
    decision_trace: list[dict[str, object]] = field(default_factory=list)


def resolve_context(rep: Any, index: SemanticIndex) -> Resolution:
    """Score evidence deterministically; ties never auto-repair."""
    identifier = str(attr(rep, "RepresentationIdentifier", "") or "").casefold()
    product = index.product_for(rep)
    scores: dict[int, int] = defaultdict(int)
    reasons: dict[int, list[str]] = defaultdict(list)
    conflicts: list[str] = []

    eligible = {
        cid: info for cid, info in index.context_info.items() if info.connected_to_project
    }
    if not eligible:
        return Resolution(Status.NOT_REPAIRABLE, None, 0.0,
                          conflicts=["No representation context connected to IfcProject"])

    # Strong evidence: valid sibling with the same identifier.
    owner = index.owner_for(rep)
    siblings = (attr(owner, "Representations", None) or
                attr(owner, "ShapeRepresentations", ()) or ())
    for sibling in siblings:
        if sibling is rep:
            continue
        sid = str(attr(sibling, "RepresentationIdentifier", "") or "").casefold()
        cid = entity_id(attr(sibling, "ContextOfItems"))
        if cid in eligible and sid == identifier and identifier:
            scores[cid] += 80
            reasons[cid].append("Matching valid sibling representation uses this context")

    # Equivalent products in this exact file.
    signature = index.signature(rep, product)
    observed = index.matching_contexts.get(signature, {})
    for cid, count in observed.items():
        if cid in eligible:
            scores[cid] += min(70, 45 + int(count) * 5)
            reasons[cid].append(
                f"{count} equivalent valid representation(s) use this context"
            )
    if len(observed) > 1:
        conflicts.append("Equivalent representations use more than one context")

    # Exact representation semantics are reusable across product classes. IFC
    # representation contexts describe the geometry view (for example Body or
    # FootPrint), not the owning product class. Same-file evidence is accepted
    # only for an exact identifier/type/item signature and a project-rooted context.
    semantic_signature = signature[1:]
    semantic_observed = index.semantic_contexts.get(semantic_signature, {})
    for cid, count in semantic_observed.items():
        if cid in eligible:
            scores[cid] += min(65, 40 + int(count) * 5)
            reasons[cid].append(
                f"{count} exact semantic peer representation(s) in this IFC use this context"
            )
    if len(semantic_observed) > 1:
        conflicts.append(
            "Exact semantic peer representations use more than one context"
        )

    # Versioned semantic evidence learned from the supplied clean samples. This is
    # supporting evidence only: the candidate must still exist in this IFC and be
    # connected to its project context graph.
    for pattern in SUPPLIED_CLEAN_PATTERNS:
        expected_signature = (
            pattern.product_class, pattern.representation_identifier,
            pattern.representation_type, pattern.item_type,
        )
        if signature != expected_signature:
            continue
        for cid, info in eligible.items():
            if ((info.identifier or "").casefold() == pattern.context_identifier and
                    (info.target_view or "").upper() == pattern.target_view):
                scores[cid] += 50
                reasons[cid].append(
                    f"{pattern.clean_representation_count} matching representations across "
                    f"{pattern.clean_file_count} supplied clean Revit samples use this "
                    "semantic context pattern"
                )

    # Identifier and target-view evidence.
    for cid, info in eligible.items():
        if identifier and (info.identifier or "").casefold() == identifier:
            scores[cid] += 30
            reasons[cid].append("Context identifier matches representation identifier")
        if identifier == "body" and (info.target_view or "").upper() == "MODEL_VIEW":
            scores[cid] += 10
            reasons[cid].append("MODEL_VIEW is compatible with a Body representation")
        if identifier == "axis" and (info.target_view or "").upper() == "GRAPH_VIEW":
            scores[cid] += 10
            reasons[cid].append("GRAPH_VIEW is compatible with an Axis representation")
        scores[cid] += 5
        reasons[cid].append("Context is connected to the active IfcProject")

    ranked = sorted(scores, key=lambda cid: (-scores[cid], cid))
    trace = [
        {
            "context_step_id": cid,
            "score": scores[cid],
            "evidence": list(reasons[cid]),
            "connected_to_project": eligible[cid].connected_to_project,
            "identifier": eligible[cid].identifier,
            "target_view": eligible[cid].target_view,
            "selected": False,
        }
        for cid in ranked
    ]
    if not ranked or scores[ranked[0]] < 25:
        return Resolution(
            Status.NOT_REPAIRABLE, None, 0.0,
            conflicts=[*conflicts, "No context has sufficient supporting evidence"],
            candidates=list(eligible.values()), decision_trace=trace,
        )
    best = ranked[0]
    second_score = scores[ranked[1]] if len(ranked) > 1 else -1
    best_score = scores[best]
    if second_score == best_score or best_score - second_score < 15:
        return Resolution(
            Status.AMBIGUOUS, None, min(0.69, best_score / 150),
            conflicts=[*conflicts, "Leading context candidates have similar evidence"],
            candidates=[eligible[cid] for cid in ranked], decision_trace=trace,
        )
    best_info = eligible[best]
    context_identifier = (best_info.identifier or "").casefold()
    target_view = (best_info.target_view or "").upper()
    incompatible_view = (
        identifier == "body" and target_view and target_view != "MODEL_VIEW"
    ) or (
        identifier == "footprint" and target_view and target_view not in {"PLAN_VIEW", "MODEL_VIEW"}
    ) or (
        identifier == "axis" and target_view and target_view not in {"GRAPH_VIEW", "MODEL_VIEW"}
    )
    if identifier and context_identifier != identifier:
        return Resolution(
            Status.NOT_REPAIRABLE, None, min(0.69, best_score / 150),
            conflicts=[*conflicts, "Selected context identifier does not match the representation"],
            candidates=[eligible[cid] for cid in ranked], decision_trace=trace,
        )
    if incompatible_view:
        return Resolution(
            Status.NOT_REPAIRABLE, None, min(0.69, best_score / 150),
            conflicts=[*conflicts, "Selected context target view is incompatible"],
            candidates=[eligible[cid] for cid in ranked], decision_trace=trace,
        )
    confidence = min(0.99, best_score / 120)
    strong_file_evidence = best_score >= 50 and confidence >= 0.70
    status = Status.SAFE if strong_file_evidence and not conflicts else Status.WARNING
    for item in trace:
        item["selected"] = item["context_step_id"] == best
        if item["selected"]:
            item["tie_break_reason"] = "Highest semantic score; STEP ID used only for stable ordering"
    return Resolution(status, index.contexts[best], confidence, reasons[best], conflicts,
                      [eligible[cid] for cid in ranked], trace)
