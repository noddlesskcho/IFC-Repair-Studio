from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import pytest

from ifc_context_repair.rules import ACTIVE_RULE
from ifc_context_repair.rules.ifc_sg import IFC_SG_RULES, IfcSgRuleContext
from ifc_context_repair.prescan import profile_step
from tests.fixtures.synthetic_ifc import build_ifc_sg_fixture


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ifcopenshell") is None,
    reason="IfcOpenShell not installed",
)


def test_direct_and_type_owned_footprint_fixture() -> None:
    import ifcopenshell

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "fixture.ifc"
        entities = build_ifc_sg_fixture(
            path,
            direct_missing=True,
            footprint_map_missing=True,
            type_owned_without_occurrences=True,
        )
        model = ifcopenshell.open(str(path))
        result = ACTIVE_RULE.detect(model, repair_mode="advanced")
    by_id = {item.representation_step_id: item for item in result.diagnoses}
    assert by_id[entities["direct"].id()].confidence_level.value == "HIGH"
    mapped = by_id[entities["mapped_rep"].id()]
    assert mapped.rule_id == "REPRESENTATION_MAP_FOOTPRINT_MISSING_CONTEXT_V1"
    assert mapped.confidence_level.value == "HIGH"


def test_report_only_audit_fixtures() -> None:
    import ifcopenshell

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "audits.ifc"
        build_ifc_sg_fixture(
            path,
            space_without_body=True,
            quantity_review=True,
            georeferencing=True,
        )
        profile = profile_step(path)
        model = ifcopenshell.open(str(path))
        context = IfcSgRuleContext(model, "IFC4", profile)
        findings = [
            finding
            for rule in IFC_SG_RULES.select(context).selected
            if rule.repair_mode == "AUDIT_ONLY"
            for finding in rule.detect(context)
        ]
    categories = {item.category for item in findings}
    assert "Space Geometry" in categories
    assert "Quantity Information" in categories
    assert "Georeferencing" in categories
