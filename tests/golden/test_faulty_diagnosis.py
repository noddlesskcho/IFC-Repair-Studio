import os
import unittest
from pathlib import Path

from ifc_context_repair.models import Status
from ifc_context_repair.repair import analyse


class FaultyGoldenDiagnosisTests(unittest.TestCase):
    def test_configured_faulty_files_resolve_safely_without_modification(self):
        raw = os.environ.get("IFC_FAULTY_FIXTURES", "")
        if not raw:
            self.skipTest("IFC_FAULTY_FIXTURES is not configured")
        for path in [Path(value) for value in raw.split(os.pathsep) if value]:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                report = analyse(path, validate=True)
                self.assertGreater(len(report.diagnoses), 0)
                self.assertTrue(all(item.status is Status.SAFE for item in report.diagnoses))
                self.assertTrue(all(item.proposed_context for item in report.diagnoses))
                self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
