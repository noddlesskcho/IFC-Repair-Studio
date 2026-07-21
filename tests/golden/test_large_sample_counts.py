import os
import unittest
from collections import Counter
from pathlib import Path

from ifc_context_repair.repair import analyse


class LargeSampleCountingTests(unittest.TestCase):
    def test_verified_slab_and_representation_counts(self):
        configured = os.environ.get("IFC_LARGE_SAMPLE")
        if not configured:
            self.skipTest("IFC_LARGE_SAMPLE is not configured")
        path = Path(configured)
        self.assertTrue(path.is_file())
        report = analyse(path, validate=False, quick=True)
        counts = report.summary_counts
        self.assertEqual(counts["ElementsScanned"], 2552)
        self.assertEqual(counts["ElementsAffected"], 2051)
        self.assertEqual(counts["RepresentationsScanned"], 4851)
        self.assertEqual(counts["AffectedRepresentations"], 3151)
        breakdown = Counter(
            (item.representation_identifier, item.representation_type)
            for item in report.diagnoses
        )
        self.assertEqual(breakdown[("Body", "SweptSolid")], 1100)
        self.assertEqual(breakdown[("FootPrint", "Curve2D")], 2051)
        self.assertEqual({item.product_class for item in report.diagnoses}, {"IfcSlab"})


if __name__ == "__main__":
    unittest.main()
