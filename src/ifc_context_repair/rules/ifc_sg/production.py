from __future__ import annotations

from typing import Any

from ...models import (
    AuditFinding,
    Diagnosis,
    RepresentationClassification,
)
from .base import IfcSgRule, IfcSgRuleContext
from .registry import IfcSgRuleRegistry


def _value(entity: Any, name: str, default: Any = None) -> Any:
    try:
        result = getattr(entity, name)
    except (AttributeError, RuntimeError):
        return default
    return default if result is None else result


def _step_id(entity: Any) -> int | None:
    try:
        return int(entity.id()) or None
    except (AttributeError, TypeError, ValueError):
        return None


class _ContextRule(IfcSgRule):
    supported_schemas = frozenset({"IFC4"})
    supported_exporter_patterns = (
        "Tested: Autodesk Revit 2024-2026 IFC+SG exporter patterns",
        "Other exporters allowed only when semantic evidence is sufficient",
    )
    supported_signatures = (
        "Body / SweptSolid",
        "Body / Tessellation",
        "FootPrint / Curve2D",
    )
    repair_capability = "Targeted ContextOfItems repair"
    confidence_requirement = "HIGH"
    known_limitations = (
        "Does not create or rebuild geometry",
        "Does not support IFC2X3 or IFC4X3 repair",
        "Ambiguous context candidates remain unchanged",
    )
    category = "Representation Context"
    maturity = "PRODUCTION"

    classification: RepresentationClassification

    def detect(self, context: IfcSgRuleContext) -> list[Diagnosis]:
        return [
            item for item in context.diagnoses
            if item.classification is self.classification
            and self._matches(item)
        ]

    def _matches(self, item: Diagnosis) -> bool:
        return True


class DirectProductMissingContextRule(_ContextRule):
    rule_id = "DIRECT_PRODUCT_MISSING_CONTEXT_V2"
    title = "Direct product missing representation context"
    purpose = "Repair missing contexts on directly owned product shape representations."
    repair_mode = "SAFE"
    classification = RepresentationClassification.DIRECT_PRODUCT


class ShapeAspectMissingContextRule(_ContextRule):
    rule_id = "SHAPE_ASPECT_PRODUCT_MISSING_CONTEXT_V1"
    title = "Shape-aspect missing representation context"
    purpose = "Repair proven missing contexts on product-owned shape aspects."
    repair_mode = "ADVANCED"
    classification = RepresentationClassification.SHAPE_ASPECT_PRODUCT


class ShapeAspectMapMissingContextRule(_ContextRule):
    rule_id = "SHAPE_ASPECT_MAP_MISSING_CONTEXT_V1"
    title = "Shape-aspect representation-map missing context"
    purpose = (
        "Repair proven missing contexts on shape-aspect representations owned "
        "through reusable representation maps."
    )
    repair_mode = "ADVANCED"
    classification = RepresentationClassification.SHAPE_ASPECT_REPRESENTATION_MAP
    known_limitations = _ContextRule.known_limitations + (
        "Requires one compatible context proven by map ownership or usage evidence",
        "Conflicting or untraceable reusable geometry remains report only",
    )


class RepresentationMapMissingContextRule(_ContextRule):
    rule_id = "REPRESENTATION_MAP_MISSING_CONTEXT_V1"
    title = "Reusable representation map missing context"
    purpose = "Repair proven missing contexts in reusable mapped geometry."
    repair_mode = "ADVANCED"
    classification = RepresentationClassification.REPRESENTATION_MAP

    def _matches(self, item: Diagnosis) -> bool:
        return not (
            str(item.representation_identifier or "").casefold() == "footprint"
            and str(item.representation_type or "").casefold() == "curve2d"
        )


class RepresentationMapFootprintRule(_ContextRule):
    rule_id = "REPRESENTATION_MAP_FOOTPRINT_MISSING_CONTEXT_V1"
    title = "Type-level FootPrint representation map missing context"
    purpose = (
        "Repair a missing FootPrint / Curve2D context where map ownership or usage, "
        "semantic peers, and project context hierarchy prove one value."
    )
    repair_mode = "ADVANCED"
    classification = RepresentationClassification.REPRESENTATION_MAP
    supported_signatures = ("FootPrint / Curve2D",)
    known_limitations = _ContextRule.known_limitations + (
        "A valid type owner without placed occurrences is treated as meaningful "
        "type-level geometry only when all other evidence agrees",
    )

    def _matches(self, item: Diagnosis) -> bool:
        return (
            str(item.representation_identifier or "").casefold() == "footprint"
            and str(item.representation_type or "").casefold() == "curve2d"
        )


class IfcSpaceBodyAuditRule(IfcSgRule):
    rule_id = "IFCSPACE_BODY_AUDIT_V1"
    title = "IfcSpace Body representation audit"
    purpose = "Report spaces without an accepted Body representation."
    maturity = "BETA"
    repair_mode = "AUDIT_ONLY"
    supported_schemas = frozenset({"IFC4"})
    supported_exporter_patterns = ("Autodesk Revit IFC+SG", "Exporter-neutral IFC4 audit")
    supported_signatures = ("IfcSpace with Body representation",)
    repair_capability = "Report only"
    confidence_requirement = "REPORT_ONLY"
    known_limitations = (
        "Does not create missing space geometry",
        "Representation acceptance is a technical pre-submission check, not regulatory approval",
    )
    category = "Space Geometry"

    def detect(self, context: IfcSgRuleContext) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        # Do not access the derived ContainedInStructure inverse here. Some
        # frozen IfcOpenShell distributions attempt to locate an EXPRESS file
        # when resolving that attribute. A single explicit relationship pass is
        # portable and also avoids repeated inverse scans for large models.
        structures_by_space: dict[int, list[Any]] = {}
        for relation in context.model.by_type("IfcRelContainedInSpatialStructure"):
            structure = _value(relation, "RelatingStructure")
            for element in _value(relation, "RelatedElements", ()) or ():
                if element is not None and element.is_a("IfcSpace"):
                    structures_by_space.setdefault(_step_id(element), []).append(structure)
        for space in context.model.by_type("IfcSpace"):
            representations = list(
                _value(_value(space, "Representation"), "Representations", ()) or ()
            )
            body = [
                rep for rep in representations
                if str(_value(rep, "RepresentationIdentifier", "")).casefold() == "body"
                and _value(rep, "ContextOfItems") is not None
                and len(_value(rep, "Items", ()) or ())
            ]
            if body:
                continue
            storeys: list[str] = []
            for structure in structures_by_space.get(_step_id(space), ()):
                if structure is not None:
                    storeys.append(
                        f"{structure.is_a()} #{_step_id(structure)} "
                        f"{_value(structure, 'Name', '')}".strip()
                    )
            reason = (
                "No representations are assigned"
                if not representations
                else "No non-empty Body representation with a valid context is assigned"
            )
            findings.append(AuditFinding(
                self.rule_id,
                self.category,
                "IfcSpace does not have an accepted Body representation",
                _step_id(space),
                "IfcSpace",
                str(_value(space, "GlobalId", "") or ""),
                str(_value(space, "Name", "") or ""),
                detail=reason,
                evidence=[
                    f"LongName: {_value(space, 'LongName', '') or '(empty)'}",
                    f"Storey: {', '.join(storeys) or 'Not resolved'}",
                    f"Assigned representations: {len(representations)}",
                ],
                schema_validity="Not automatically classified as a schema error",
                rendering_impact="Space geometry may be unavailable",
                downstream_impact="May affect space geometry extraction and coordination",
                submission_risk="Review for IFC+SG pre-submission expectations",
                repair_priority="Medium",
                data={
                    "long_name": str(_value(space, "LongName", "") or ""),
                    "storey": storeys,
                    "representation_count": len(representations),
                    "reason": reason,
                },
            ))
        return findings


class BaseQuantityAuditRule(IfcSgRule):
    rule_id = "BASE_QUANTITY_AUDIT_V1"
    title = "Base quantity information audit"
    purpose = "Report quantity-set naming and MethodOfMeasurement information for review."
    maturity = "BETA"
    repair_mode = "AUDIT_ONLY"
    supported_schemas = frozenset({"IFC4"})
    supported_exporter_patterns = ("Exporter-neutral IFC4 audit",)
    supported_signatures = ("IfcElementQuantity", "Qto_*", "BaseQuantities")
    repair_capability = "Report only"
    confidence_requirement = "REPORT_ONLY"
    known_limitations = (
        "Does not infer or create quantities",
        "Validator expectations can depend on submission scope",
    )
    category = "Quantity Information"

    def detect(self, context: IfcSgRuleContext) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        for quantity_set in context.model.by_type("IfcElementQuantity"):
            name = str(_value(quantity_set, "Name", "") or "")
            method = str(_value(quantity_set, "MethodOfMeasurement", "") or "")
            if method.casefold() == "basequantities":
                continue
            detail = (
                "MethodOfMeasurement is empty"
                if not method
                else f"MethodOfMeasurement is '{method}', not 'BaseQuantities'"
            )
            findings.append(AuditFinding(
                self.rule_id,
                self.category,
                "Quantity information requires review",
                _step_id(quantity_set),
                "IfcElementQuantity",
                str(_value(quantity_set, "GlobalId", "") or ""),
                name,
                detail=detail,
                evidence=[
                    f"Quantity-set name: {name or '(empty)'}",
                    f"MethodOfMeasurement: {method or '(empty)'}",
                    f"Quantity entries: {len(_value(quantity_set, 'Quantities', ()) or ())}",
                ],
                schema_validity="Report-only information check",
                rendering_impact="None",
                downstream_impact="May affect quantity interpretation or validator expectations",
                submission_risk="Confirm the applicable CORENET X submission expectation",
                repair_priority="Review",
                data={
                    "method_of_measurement": method,
                    "looks_like_qto": name.casefold().startswith("qto_"),
                },
            ))
        return findings


class GeoreferencingAuditRule(IfcSgRule):
    rule_id = "IFCSG_GEOREFERENCING_AUDIT_V1"
    title = "IFC+SG georeferencing audit"
    purpose = "Report georeferencing entity presence, references, and coordinate values."
    maturity = "BETA"
    repair_mode = "AUDIT_ONLY"
    supported_schemas = frozenset({"IFC4"})
    supported_exporter_patterns = ("Exporter-neutral IFC4 audit",)
    supported_signatures = ("IfcProjectedCRS", "IfcMapConversion")
    repair_capability = "Report only"
    confidence_requirement = "REPORT_ONLY"
    known_limitations = (
        "Presence does not prove coordinate correctness",
        "Does not validate values against an external survey or authority",
    )
    category = "Georeferencing"

    def detect(self, context: IfcSgRuleContext) -> list[AuditFinding]:
        crs_entities = list(context.model.by_type("IfcProjectedCRS"))
        conversions = list(context.model.by_type("IfcMapConversion"))
        if not crs_entities:
            return [AuditFinding(
                self.rule_id,
                self.category,
                "IfcProjectedCRS was not found",
                None,
                "IfcProjectedCRS",
                detail="No projected coordinate reference system entity is present.",
                evidence=[f"IfcMapConversion entities present: {len(conversions)}"],
                schema_validity="Not sufficient by itself to classify overall IFC validity",
                rendering_impact="Usually low for local geometry",
                downstream_impact="Geospatial placement may be unavailable or ambiguous",
                submission_risk="Review IFC+SG georeferencing requirements",
                repair_priority="High review priority",
            )]
        findings: list[AuditFinding] = []
        for conversion in conversions:
            source_crs = _value(conversion, "SourceCRS")
            target_crs = _value(conversion, "TargetCRS")
            data = {
                "source_crs_step_id": _step_id(source_crs),
                "target_crs_step_id": _step_id(target_crs),
                "eastings": _value(conversion, "Eastings"),
                "northings": _value(conversion, "Northings"),
                "orthogonal_height": _value(conversion, "OrthogonalHeight"),
                "x_axis_abscissa": _value(conversion, "XAxisAbscissa"),
                "x_axis_ordinate": _value(conversion, "XAxisOrdinate"),
                "scale": _value(conversion, "Scale"),
                "crs_name": str(_value(target_crs, "Name", "") or ""),
                "crs_description": str(_value(target_crs, "Description", "") or ""),
            }
            integrity = source_crs is not None and target_crs in crs_entities
            findings.append(AuditFinding(
                self.rule_id,
                self.category,
                "Georeferencing relationship inspected",
                _step_id(conversion),
                "IfcMapConversion",
                name=data["crs_name"],
                detail=(
                    "References are internally connected; coordinate interpretation "
                    "still requires project confirmation."
                    if integrity else
                    "SourceCRS or TargetCRS reference is missing or inconsistent."
                ),
                evidence=[
                    f"SourceCRS: #{data['source_crs_step_id'] or '?'}",
                    f"TargetCRS: #{data['target_crs_step_id'] or '?'}",
                    f"Eastings/Northings: {data['eastings']} / {data['northings']}",
                    f"OrthogonalHeight: {data['orthogonal_height']}",
                    f"Axis: {data['x_axis_abscissa']} / {data['x_axis_ordinate']}",
                    f"Scale: {data['scale']}",
                ],
                schema_validity=(
                    "References present" if integrity else "Reference integrity issue detected"
                ),
                rendering_impact="Usually low for local element geometry",
                downstream_impact="Affects map placement and coordinate interpretation",
                submission_risk="Coordinate values require project-specific confirmation",
                repair_priority="Review",
                data=data,
            ))
        if not conversions:
            findings.append(AuditFinding(
                self.rule_id,
                self.category,
                "IfcMapConversion was not found",
                None,
                "IfcMapConversion",
                detail="Projected CRS exists without a map-conversion entity.",
                evidence=[f"IfcProjectedCRS entities present: {len(crs_entities)}"],
                submission_risk="Review IFC+SG georeferencing requirements",
                repair_priority="High review priority",
            ))
        return findings


def build_registry() -> IfcSgRuleRegistry:
    registry = IfcSgRuleRegistry()
    for rule in (
        DirectProductMissingContextRule(),
        ShapeAspectMissingContextRule(),
        ShapeAspectMapMissingContextRule(),
        RepresentationMapMissingContextRule(),
        RepresentationMapFootprintRule(),
        IfcSpaceBodyAuditRule(),
        BaseQuantityAuditRule(),
        GeoreferencingAuditRule(),
    ):
        registry.register(rule)
    return registry


IFC_SG_RULES = build_registry()
