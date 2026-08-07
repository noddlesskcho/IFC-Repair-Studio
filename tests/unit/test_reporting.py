import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.models import (
    AuditFinding, ConfidenceLevel, ContextInfo, Diagnosis, FileAssessment,
    IfcSgAssessment, IfcSgClassification, ProcessingStrategy, RunReport, Status,
)
from ifc_context_repair.reporting import HTMLReportBuilder, write_bundle


class ReportingTests(unittest.TestCase):
    @staticmethod
    def report() -> RunReport:
        diagnosis = Diagnosis(
            representation_step_id=42,
            representation_identifier="Body",
            representation_type="SweptSolid",
            item_count=1,
            item_classes=["IfcExtrudedAreaSolid"],
            current_context_step_id=None,
            product_class="IfcSlab",
            product_step_id=20,
            product_global_id="3ExampleGlobalId",
            product_name="Level 01 Slab",
            rule_id="SLAB_MISSING_SHAPE_CONTEXT_V1",
            proposed_context=ContextInfo(10, "IfcGeometricRepresentationSubContext", "Body", "Model"),
            status=Status.REPAIRED,
            confidence=1.0,
            evidence=["Direct IfcSlab ownership"],
            validation_result="Targeted output verified",
            repaired=True,
            confidence_level=ConfidenceLevel.HIGH,
        )
        return RunReport(
            source="C:/project/sample.ifc", output="C:/project/sample_repaired.ifc",
            schema="IFC4", started_at="2026-07-19T10:00:00+00:00",
            finished_at="2026-07-19T10:00:36+00:00",
            durations={"ifc_opening": 24.2, "repair_assignment": .1,
                       "temporary_ifc_serialization": 12.4,
                       "targeted_verification": .01},
            summary_counts={"ElementsScanned": 2552, "ElementsAffected": 2051,
                            "RepresentationsScanned": 4851,
                            "AffectedRepresentations": 3151,
                            "AutomaticallyRepairable": 3151,
                            "SuccessfullyRepaired": 3151,
                            "TargetedIssuesRemaining": 0},
            active_rule_id="SLAB_MISSING_SHAPE_CONTEXT_V1",
            active_rule_version="1.0", input_size=652895459, output_size=652901761,
            classification_counts={
                "DIRECT_PRODUCT": {
                    "detected": 3151, "high_confidence": 3151,
                    "auto_repair": 3151, "repaired": 3151, "remaining": 0,
                }
            },
            targeted_verification={"passed": True, "intended": 3151,
                                   "verified": 3151, "remaining": 0, "messages": []},
            diagnoses=[diagnosis], repair_mode="Targeted STEP attribute patch",
            environment={"python_version": "3.12", "ifcopenshell_version": "0.8"},
            file_assessment=FileAssessment(
                "sample.ifc", "sample.ifc", "IFC", "IFC4", 652895459,
                "Large", ProcessingStrategy.HYBRID,
                ifc_sg=IfcSgAssessment(
                    IfcSgClassification.LIKELY,
                    evidence=["SGPset_ property sets found"],
                    likely_exporter="Autodesk Revit",
                ),
            ),
            audit_findings=[AuditFinding(
                "IFCSPACE_BODY_AUDIT_V1", "Space Geometry",
                "Space Body requires review", 99, "IfcSpace",
                detail="No Body representation", submission_risk="Review",
            )],
        )

    def test_default_bundle_contains_only_pdf_and_html(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = write_bundle(self.report(), Path(folder) / "sample_repair_report")
            self.assertEqual(set(paths), {"pdf", "html"})
            self.assertTrue(paths["pdf"].is_file())
            self.assertTrue(paths["html"].is_file())
            self.assertFalse((Path(folder) / "sample_repair_report.csv").exists())
            self.assertFalse((Path(folder) / "sample_repair_report.json").exists())

    def test_html_has_records_and_interactive_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = write_bundle(self.report(), Path(folder) / "sample_repair_report")
            html = paths["html"].read_text(encoding="utf-8")
            self.assertIn("3ExampleGlobalId", html)
            self.assertIn("Export filtered CSV", html)
            self.assertIn("Search STEP ID", html)
            self.assertNotIn("Export filtered JSON", html)
            self.assertIn('id="elementFilter"', html)
            self.assertIn('id="representationFilter"', html)
            self.assertNotIn('id="classificationFilter"', html)
            self.assertNotIn('id="confidenceFilter"', html)
            self.assertNotIn('id="verifyFilter"', html)
            self.assertIn('id="verification"', html)
            self.assertIn("outcome-grid", html)
            self.assertIn("IFC+SG File Assessment", html)
            self.assertIn("Space Body requires review", html)
            self.assertNotIn(f" {chr(0x00F9)} ", html)
            self.assertIn("Body / SweptSolid", html)
            self.assertIn(
                "A repaired IFC should still undergo the normal submission validation process",
                html,
            )
            for tab in (
                "Summary", "Repairs Applied",
                "Items to Review", "Verification", "Technical Details",
            ):
                self.assertIn(f">{tab}</a>", html)
            self.assertNotIn('id="items-review"', html)
            self.assertNotIn(">Unresolved Geometry</a>", html)
            self.assertIn("SUPPORTED", html)
            self.assertNotIn("Experimental Findings", html)
            self.assertNotIn("Compatibility Test Matrix", html)
            self.assertIn("IfcShapeAspect and IfcRepresentationMap", html)
            self.assertIn("REPORT ONLY", html)
            self.assertIn("No IFC change was applied", html)
            self.assertIn('data-sort="outcome"', html)
            self.assertIn("REVIEW IN REVIT", html)
            self.assertNotIn("C:/project/", html)

    def test_geometry_records_have_simplified_columns_scrollbars_and_sort_arrows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "records.html"
            HTMLReportBuilder().build(self.report(), path)
            html = path.read_text(encoding="utf-8")

            self.assertIn('id="recordsTopScroll"', html)
            self.assertIn('id="recordsTableWrap"', html)
            self.assertIn('id="recordsTable"', html)
            self.assertIn('aria-sort="ascending"', html)
            self.assertIn("sort-indicator", html)
            self.assertIn("Repair type:", html)
            self.assertNotIn('data-sort="rule"', html)
            self.assertNotIn('data-sort="confidence"', html)
            self.assertNotIn('data-sort="verification"', html)
            self.assertNotIn('data-sort="old_context"', html)
            self.assertNotIn('data-sort="new_context"', html)
            for heading in (
                "Outcome", "STEP ID", "GlobalId", "Element", "Name",
                "Representation", "Details",
            ):
                self.assertIn(f">{heading}<span class=\"sort-indicator\">", html)

    def test_unresolved_geometry_section_only_appears_when_needed(self):
        report = self.report()
        report.summary_counts["TargetedIssuesRemaining"] = 2
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unresolved.html"
            HTMLReportBuilder().build(report, path)
            html = path.read_text(encoding="utf-8")

            self.assertIn(">Unresolved Geometry</a>", html)
            self.assertIn('id="items-review"', html)
            self.assertIn(
                "2</strong> geometry reference(s) could not be repaired automatically",
                html,
            )

    def test_html_groups_large_audit_lists_and_paginates_entity_ids(self):
        report = self.report()
        report.audit_findings = [
            AuditFinding(
                "BASE_QUANTITY_AUDIT_V1",
                "Quantity Information",
                "Quantity information requires review",
                step_id,
                "IfcElementQuantity",
                detail="MethodOfMeasurement is empty",
                submission_risk=(
                    "Confirm the applicable CORENET X submission expectation"
                ),
            )
            for step_id in range(1, 5001)
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large_audit.html"
            HTMLReportBuilder().build(report, path)
            html = path.read_text(encoding="utf-8")

            self.assertIn("condensed into <strong>1</strong> issue group", html)
            self.assertIn("Groups per page", html)
            self.assertIn("Entity page", html)
            self.assertIn('"count":5000', html)
            self.assertIn('"entity_ids":[1,2,3', html)
            self.assertEqual(html.count("BASE_QUANTITY_AUDIT_V1"), 1)
            self.assertLess(path.stat().st_size, 1_000_000)


if __name__ == "__main__":
    unittest.main()
