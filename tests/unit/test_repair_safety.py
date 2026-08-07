from __future__ import annotations

import unittest

from ifc_context_repair.indirect import is_repairable_in_mode
from ifc_context_repair.models import (
    ConfidenceLevel,
    ContextInfo,
    Diagnosis,
    RepresentationClassification,
    Status,
)
from ifc_context_repair.repair_safety import apply_signature_policy


def diagnosis(
    classification: RepresentationClassification,
    identifier: str,
    representation_type: str,
) -> Diagnosis:
    item = Diagnosis(
        representation_step_id=100,
        representation_identifier=identifier,
        representation_type=representation_type,
        item_count=1,
        item_classes=["IfcFacetedBrep"],
        current_context_step_id=None,
        classification=classification,
        proposed_context=ContextInfo(
            step_id=26,
            entity_type="IfcGeometricRepresentationSubContext",
            identifier=identifier,
            context_type="Model",
            dimension=2 if identifier.casefold() == "footprint" else 3,
        ),
        status=Status.SAFE,
        confidence=0.9,
        confidence_level=ConfidenceLevel.HIGH,
    )
    apply_signature_policy(item)
    return item


class RepairSafetyTests(unittest.TestCase):
    def test_only_viewer_approved_direct_sweptsolid_is_production_enabled(self) -> None:
        item = diagnosis(
            RepresentationClassification.DIRECT_PRODUCT, "Body", "SweptSolid"
        )
        self.assertTrue(item.production_enabled)
        self.assertEqual(item.safety_level, "Production-Safe")
        self.assertTrue(is_repairable_in_mode(item, "production"))

    def test_direct_tessellation_is_experimental(self) -> None:
        item = diagnosis(
            RepresentationClassification.DIRECT_PRODUCT, "BODY", "TESSELLATION"
        )
        self.assertFalse(item.production_enabled)
        self.assertEqual(item.repair_signature, "DirectProduct/Body/Tessellation")
        self.assertFalse(is_repairable_in_mode(item, "production"))
        self.assertTrue(is_repairable_in_mode(item, "compat_all"))

    def test_shape_aspect_is_not_enabled_by_legacy_advanced_mode(self) -> None:
        item = diagnosis(
            RepresentationClassification.SHAPE_ASPECT_PRODUCT,
            "Body",
            "SweptSolid",
        )
        self.assertEqual(item.safety_level, "Experimental")
        self.assertFalse(is_repairable_in_mode(item, "advanced"))
        self.assertTrue(
            is_repairable_in_mode(item, "compat_shapeaspect_sweptsolid")
        )

    def test_representation_map_footprint_is_isolated(self) -> None:
        item = diagnosis(
            RepresentationClassification.REPRESENTATION_MAP,
            "FootPrint",
            "Curve2D",
        )
        self.assertFalse(is_repairable_in_mode(item, "production"))
        self.assertTrue(is_repairable_in_mode(item, "compat_footprint"))
        self.assertFalse(
            is_repairable_in_mode(item, "compat_representationmap_body")
        )

    def test_ambiguous_case_remains_report_only(self) -> None:
        item = diagnosis(
            RepresentationClassification.AMBIGUOUS, "Body", "SweptSolid"
        )
        item.status = Status.AMBIGUOUS
        item.confidence_level = ConfidenceLevel.AMBIGUOUS
        apply_signature_policy(item)
        self.assertEqual(item.safety_level, "Report Only")
        self.assertFalse(is_repairable_in_mode(item, "compat_all"))


if __name__ == "__main__":
    unittest.main()
