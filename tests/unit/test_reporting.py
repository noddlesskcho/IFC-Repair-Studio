import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.models import ContextInfo, Diagnosis, RunReport, Status
from ifc_context_repair.reporting import write_bundle


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
            targeted_verification={"passed": True, "intended": 3151,
                                   "verified": 3151, "remaining": 0, "messages": []},
            diagnoses=[diagnosis], repair_mode="Targeted STEP attribute patch",
            environment={"python_version": "3.12", "ifcopenshell_version": "0.8"},
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
            self.assertIn("Export filtered JSON", html)
            self.assertIn("Search STEP ID", html)


if __name__ == "__main__":
    unittest.main()
