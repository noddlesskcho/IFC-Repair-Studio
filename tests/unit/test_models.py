import unittest

from ifc_context_repair.models import Diagnosis, RunReport, Status


class ReportSerializationTests(unittest.TestCase):
    def test_run_report_serializes_without_recursion(self):
        report = RunReport(source="model.ifc", diagnoses=[Diagnosis(
            representation_step_id=1, representation_identifier="Body",
            representation_type="SweptSolid", item_count=0, item_classes=[],
            current_context_step_id=None, status=Status.WARNING,
        )])
        value = report.to_dict()
        self.assertEqual(value["diagnoses"][0]["status"], "Repairable with warning")


if __name__ == "__main__":
    unittest.main()
