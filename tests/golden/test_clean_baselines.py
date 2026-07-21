import os
import unittest
from pathlib import Path

from ifc_context_repair.parser import open_model
from ifc_context_repair.prescan import scan_step
from ifc_context_repair.validator import validate_schema


class CleanBaselineGoldenTests(unittest.TestCase):
    def test_configured_clean_files_have_valid_representation_contexts(self):
        raw = os.environ.get("IFC_CLEAN_FIXTURES", "")
        if not raw:
            self.skipTest("IFC_CLEAN_FIXTURES is not configured")
        paths = [Path(value) for value in raw.split(os.pathsep) if value]
        self.assertGreater(len(paths), 0)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertEqual(scan_step(path), [])
                model = open_model(path)
                self.assertEqual(validate_schema(model), [])
                for representation in model.by_type("IfcShapeRepresentation"):
                    self.assertIsNotNone(representation.ContextOfItems)


if __name__ == "__main__":
    unittest.main()
