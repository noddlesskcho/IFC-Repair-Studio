from __future__ import annotations

from dataclasses import dataclass, field

from .base import IfcSgRule, IfcSgRuleContext


@dataclass(slots=True)
class RuleSelection:
    selected: list[IfcSgRule] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


class IfcSgRuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, IfcSgRule] = {}

    def register(self, rule: IfcSgRule) -> None:
        if rule.rule_id in self._rules:
            raise ValueError(f"Duplicate IFC+SG rule ID: {rule.rule_id}")
        self._rules[rule.rule_id] = rule

    def all(self) -> tuple[IfcSgRule, ...]:
        return tuple(self._rules.values())

    def select(self, context: IfcSgRuleContext) -> RuleSelection:
        selection = RuleSelection()
        counts = context.profile.entity_counts
        missing = len(context.profile.candidates)
        for rule in self.all():
            if not rule.is_applicable(context):
                selection.skipped[rule.rule_id] = (
                    f"Unsupported schema {context.schema or 'unknown'}"
                )
                continue
            if "MISSING_CONTEXT" in rule.rule_id and not missing:
                selection.skipped[rule.rule_id] = "No missing ContextOfItems found in pre-scan"
                continue
            if "SHAPE_ASPECT" in rule.rule_id and not counts.get("IFCSHAPEASPECT"):
                selection.skipped[rule.rule_id] = "No IfcShapeAspect entities found"
                continue
            if "REPRESENTATION_MAP" in rule.rule_id and not counts.get(
                "IFCREPRESENTATIONMAP"
            ):
                selection.skipped[rule.rule_id] = "No IfcRepresentationMap entities found"
                continue
            if rule.rule_id == "IFCSPACE_BODY_AUDIT_V1" and not counts.get("IFCSPACE"):
                selection.skipped[rule.rule_id] = "No IfcSpace entities found"
                continue
            if rule.rule_id == "BASE_QUANTITY_AUDIT_V1" and not counts.get(
                "IFCELEMENTQUANTITY"
            ):
                selection.skipped[rule.rule_id] = "No IfcElementQuantity entities found"
                continue
            selection.selected.append(rule)
        return selection
