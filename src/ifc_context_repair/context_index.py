from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .models import ContextInfo


def attr(entity: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(entity, name, default)
    except Exception:
        return default


def entity_id(entity: Any | None) -> int | None:
    if entity is None:
        return None
    try:
        return int(entity.id())
    except Exception:
        return None


def entity_type(entity: Any | None) -> str | None:
    if entity is None:
        return None
    try:
        return str(entity.is_a())
    except Exception:
        return None


@dataclass
class SemanticIndex:
    contexts: dict[int, Any] = field(default_factory=dict)
    context_info: dict[int, ContextInfo] = field(default_factory=dict)
    project_context_ids: set[int] = field(default_factory=set)
    rep_owner: dict[int, Any] = field(default_factory=dict)
    owner_product: dict[int, Any] = field(default_factory=dict)
    usage: Counter[tuple[str, str, str, str, int]] = field(default_factory=Counter)
    matching_contexts: dict[tuple[str, str, str, str], Counter[int]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    semantic_contexts: dict[tuple[str, str, str], Counter[int]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    product_scope: dict[int, str] = field(default_factory=dict)
    products_by_scope: Counter[str] = field(default_factory=Counter)
    representations_by_scope: Counter[str] = field(default_factory=Counter)
    total_shape_representations: int = 0
    total_products: int = 0

    @classmethod
    def build(
        cls,
        model: Any,
        representations: list[Any] | None = None,
        products: list[Any] | None = None,
    ) -> "SemanticIndex":
        index = cls()
        root_contexts: set[int] = set()
        for project in model.by_type("IfcProject"):
            for context in attr(project, "RepresentationContexts", ()) or ():
                cid = entity_id(context)
                if cid:
                    root_contexts.add(cid)
        index.project_context_ids.update(root_contexts)

        all_contexts = list(model.by_type("IfcGeometricRepresentationContext"))
        # by_type normally includes subtypes; include explicitly for bindings that do not.
        known = {entity_id(c) for c in all_contexts}
        for context in model.by_type("IfcGeometricRepresentationSubContext"):
            if entity_id(context) not in known:
                all_contexts.append(context)
        for context in all_contexts:
            cid = entity_id(context)
            if not cid:
                continue
            parent = attr(context, "ParentContext")
            parent_id = entity_id(parent)
            connected = cid in root_contexts or parent_id in root_contexts
            if connected:
                index.project_context_ids.add(cid)
            index.contexts[cid] = context
            index.context_info[cid] = ContextInfo(
                step_id=cid,
                entity_type=entity_type(context) or "Unknown",
                identifier=attr(context, "ContextIdentifier"),
                context_type=attr(context, "ContextType"),
                target_view=str(attr(context, "TargetView")) if attr(context, "TargetView") else None,
                parent_step_id=parent_id,
                dimension=attr(context, "CoordinateSpaceDimension"),
                connected_to_project=connected,
            )

        # A targeted product list avoids building inverse ownership for every
        # object in a large multidisciplinary IFC. Product policies supply their
        # supported instances here and follow the direct standard chain:
        # product.Representation -> ProductDefinitionShape.Representations.
        if products is not None:
            for product in products:
                owner = attr(product, "Representation")
                oid = entity_id(owner)
                if not oid:
                    continue
                index.owner_product[oid] = product
                for rep in attr(owner, "Representations", ()) or ():
                    rid = entity_id(rep)
                    if rid:
                        index.rep_owner[rid] = owner
        else:
            # General-purpose path retained for library/CLI compatibility.
            for owner in model.by_type("IfcProductDefinitionShape"):
                for rep in attr(owner, "Representations", ()) or ():
                    rid = entity_id(rep)
                    if rid:
                        index.rep_owner[rid] = owner
                oid = entity_id(owner)
                if oid:
                    for inverse in model.get_inverse(owner):
                        if entity_id(attr(inverse, "Representation")) == oid:
                            index.owner_product[oid] = inverse
                            break
            for rep_map in model.by_type("IfcRepresentationMap"):
                rep = attr(rep_map, "MappedRepresentation")
                rid = entity_id(rep)
                if rid:
                    index.rep_owner.setdefault(rid, rep_map)
            for aspect in model.by_type("IfcShapeAspect"):
                for rep in attr(aspect, "ShapeRepresentations", ()) or ():
                    rid = entity_id(rep)
                    if rid:
                        index.rep_owner.setdefault(rid, aspect)

        for rep in (representations if representations is not None
                    else model.by_type("IfcShapeRepresentation")):
            context = attr(rep, "ContextOfItems")
            cid = entity_id(context)
            if not cid or cid not in index.contexts:
                continue
            product = index.product_for(rep)
            key = index.signature(rep, product)
            index.matching_contexts[key][cid] += 1
            index.semantic_contexts[key[1:]][cid] += 1
            index.usage[(*key, cid)] += 1
        return index

    def owner_for(self, rep: Any) -> Any | None:
        return self.rep_owner.get(entity_id(rep) or -1)

    def product_for(self, rep: Any) -> Any | None:
        owner = self.owner_for(rep)
        if entity_type(owner) == "IfcShapeAspect":
            owner = attr(owner, "PartOfProductDefinitionShape")
        return self.owner_product.get(entity_id(owner) or -1)

    @staticmethod
    def signature(rep: Any, product: Any | None) -> tuple[str, str, str, str]:
        items = attr(rep, "Items", ()) or ()
        first_item = entity_type(items[0]) if items else ""
        return (
            (entity_type(product) or "").casefold(),
            str(attr(rep, "RepresentationIdentifier", "") or "").casefold(),
            str(attr(rep, "RepresentationType", "") or "").casefold(),
            (first_item or "").casefold(),
        )
