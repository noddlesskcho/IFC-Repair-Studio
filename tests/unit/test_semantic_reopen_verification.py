from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from ifc_context_repair.compatibility_outputs import COMPATIBILITY_PROFILES
from ifc_context_repair.models import ContextInfo, Diagnosis
from ifc_context_repair.repair import _semantic_counts, _verify_semantic_reopen


class Entity:
    def __init__(self, step_id: int, entity_type: str, **values: object) -> None:
        self._step_id = step_id
        self._entity_type = entity_type
        for key, value in values.items():
            setattr(self, key, value)

    def id(self) -> int:
        return self._step_id

    def is_a(self) -> str:
        return self._entity_type


class Model:
    def __init__(self, counts: dict[str, int], representation: Entity) -> None:
        self.counts = counts
        self.representation = representation

    def __iter__(self):
        return iter(range(self.counts["TotalEntities"]))

    def by_type(self, entity_type: str):
        return [object()] * self.counts[entity_type]

    def by_id(self, step_id: int) -> Entity:
        if step_id != self.representation.id():
            raise KeyError(step_id)
        return self.representation


class SemanticReopenVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.counts = {
            "TotalEntities": 20,
            "IfcProduct": 2,
            "IfcShapeRepresentation": 3,
            "IfcRepresentationItem": 4,
            "IfcRelationship": 5,
            "GeometryItems": 4,
        }
        self.context = Entity(
            26,
            "IfcGeometricRepresentationSubContext",
            CoordinateSpaceDimension=3,
        )
        self.representation = Entity(
            100, "IfcShapeRepresentation", ContextOfItems=self.context
        )
        self.diagnosis = Diagnosis(
            representation_step_id=100,
            representation_identifier="Body",
            representation_type="SweptSolid",
            item_count=1,
            item_classes=["IfcExtrudedAreaSolid"],
            current_context_step_id=None,
            proposed_context=ContextInfo(
                26,
                "IfcGeometricRepresentationSubContext",
                "Body",
                "Model",
                dimension=3,
            ),
        )

    def test_reopen_and_entity_counts_must_match(self) -> None:
        model = Model(self.counts, self.representation)
        before = _semantic_counts(model)
        with patch("ifc_context_repair.repair.open_model", return_value=model):
            result, reopened = _verify_semantic_reopen(
                Path("output.ifc"), before, [self.diagnosis]
            )
        self.assertIs(reopened, model)
        self.assertTrue(result["passed"])
        self.assertEqual(result["count_differences"], {})

    def test_entity_count_change_fails_verification(self) -> None:
        model = Model({**self.counts, "TotalEntities": 21}, self.representation)
        with patch("ifc_context_repair.repair.open_model", return_value=model):
            result, _ = _verify_semantic_reopen(
                Path("output.ifc"), self.counts, [self.diagnosis]
            )
        self.assertFalse(result["passed"])
        self.assertIn("TotalEntities", result["count_differences"])

    def test_required_isolated_output_profiles_are_named(self) -> None:
        suffixes = {item[1] for item in COMPATIBILITY_PROFILES}
        self.assertEqual(
            suffixes,
            {
                "DIRECT_PRODUCT_ONLY",
                "TEST_SHAPEASPECT_SWEPTSOLID",
                "TEST_SHAPEASPECT_TESSELLATION",
                "TEST_REPRESENTATIONMAP_BODY",
                "TEST_FOOTPRINT",
                "TEST_ALL_REPAIRS",
            },
        )


if __name__ == "__main__":
    unittest.main()
