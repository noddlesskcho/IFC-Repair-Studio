from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures.synthetic_ifc import build_ifc_sg_fixture


@unittest.skipUnless(importlib.util.find_spec("ifcopenshell"), "IfcOpenShell not installed")
class PreparedAnalysisTests(unittest.TestCase):
    def test_repair_reuses_review_and_only_reopens_repaired_output(self) -> None:
        from ifc_context_repair.config import RepairConfig
        from ifc_context_repair.parser import open_model
        from ifc_context_repair.repair import prepare_repair_analysis, repair_file

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ifc"
            output = Path(folder) / "source_repaired.ifc"
            build_ifc_sg_fixture(source, direct_missing=True)

            prepared = prepare_repair_analysis(source)
            self.assertFalse(hasattr(prepared, "model"))
            self.assertEqual(
                prepared.report_copy().system_diagnostics[
                    "prepared_analysis_model_retained"
                ],
                False,
            )

            with patch(
                "ifc_context_repair.repair.open_model", wraps=open_model
            ) as mocked_open:
                report = repair_file(
                    RepairConfig(source=source, output=output),
                    prepared_analysis=prepared,
                )

            # The reviewed source is not parsed again. The one remaining open is
            # the mandatory independent semantic verification of repaired output.
            self.assertEqual(mocked_open.call_count, 1)
            self.assertTrue(report.system_diagnostics["analysis_reused"])
            self.assertTrue(report.targeted_verification["passed"])
            self.assertTrue(report.change_audit["passed"])
            self.assertTrue(output.is_file())

    def test_changed_source_is_rejected_before_output_creation(self) -> None:
        from ifc_context_repair.config import RepairConfig
        from ifc_context_repair.errors import OutputError
        from ifc_context_repair.repair import prepare_repair_analysis, repair_file

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ifc"
            output = Path(folder) / "source_repaired.ifc"
            build_ifc_sg_fixture(source, direct_missing=True)
            prepared = prepare_repair_analysis(source)
            source.write_bytes(source.read_bytes() + b"\r\n")

            with self.assertRaisesRegex(OutputError, "changed after review"):
                repair_file(
                    RepairConfig(source=source, output=output),
                    prepared_analysis=prepared,
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
