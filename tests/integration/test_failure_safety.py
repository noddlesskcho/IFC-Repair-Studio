import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ifc_context_repair.config import RepairConfig
from ifc_context_repair.errors import CancelledError, OutputError
from ifc_context_repair.repair import repair_file


@unittest.skipUnless(importlib.util.find_spec("ifcopenshell"), "IfcOpenShell not installed")
class FailureSafetyTests(unittest.TestCase):
    @staticmethod
    def _fixture(path: Path) -> None:
        import ifcopenshell

        model = ifcopenshell.file(schema="IFC4")
        point = model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
        axis = model.create_entity("IfcAxis2Placement3D", Location=point)
        context = model.create_entity(
            "IfcGeometricRepresentationContext", ContextIdentifier="Model",
            ContextType="Model", CoordinateSpaceDimension=3, Precision=1e-5,
            WorldCoordinateSystem=axis,
        )
        model.create_entity(
            "IfcProject", GlobalId=ifcopenshell.guid.new(),
            RepresentationContexts=[context],
        )
        sub = model.create_entity(
            "IfcGeometricRepresentationSubContext", ContextIdentifier="Body",
            ContextType="Model", ParentContext=context, TargetView="MODEL_VIEW",
        )
        item = model.create_entity(
            "IfcBoundingBox", Corner=point, XDim=1.0, YDim=1.0, ZDim=1.0
        )
        valid = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=sub,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[item],
        )
        invalid = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=sub,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[item],
        )
        shape = model.create_entity(
            "IfcProductDefinitionShape", Representations=[valid, invalid]
        )
        model.create_entity(
            "IfcSlab", GlobalId=ifcopenshell.guid.new(), Representation=shape
        )
        model.write(str(path))
        data = path.read_bytes()
        data = data.replace(
            f"#{invalid.id()}=IFCSHAPEREPRESENTATION(#{sub.id()},".encode(),
            f"#{invalid.id()}=IFCSHAPEREPRESENTATION($,".encode(), 1,
        )
        path.write_bytes(data)

    def test_temporary_write_failure_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.ifc"
            output = Path(folder) / "sample_repaired.ifc"
            self._fixture(source)
            before = source.read_bytes()
            with patch(
                "ifc_context_repair.repair.apply_patch_plan",
                side_effect=OSError("simulated temporary write failure"),
            ):
                with self.assertRaises(OSError):
                    repair_file(RepairConfig(source=source, output=output))
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).glob(".*.tmp.ifc")), [])

    def test_disk_full_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.ifc"
            output = Path(folder) / "sample_repaired.ifc"
            self._fixture(source)
            before = source.read_bytes()
            with patch(
                "ifc_context_repair.repair.shutil.disk_usage",
                return_value=SimpleNamespace(free=0),
            ):
                with self.assertRaises(OutputError):
                    repair_file(RepairConfig(source=source, output=output))
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(output.exists())

    def test_report_failure_keeps_repaired_output_and_original(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.ifc"
            output = Path(folder) / "sample_repaired.ifc"
            self._fixture(source)
            before = source.read_bytes()
            with patch(
                "ifc_context_repair.repair.write_pdf",
                side_effect=OSError("simulated report failure"),
            ):
                report = repair_file(RepairConfig(source=source, output=output))
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(output.exists())
            self.assertTrue(any("Report generation failed" in item for item in report.errors))

    def test_cancelled_scan_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.ifc"
            output = Path(folder) / "sample_repaired.ifc"
            self._fixture(source)
            before = source.read_bytes()
            with self.assertRaises(CancelledError):
                repair_file(
                    RepairConfig(source=source, output=output), cancelled=lambda: True
                )
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(output.exists())

    def test_locked_destination_preserves_source_and_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.ifc"
            output = Path(folder) / "sample_repaired.ifc"
            self._fixture(source)
            before = source.read_bytes()
            output.write_bytes(b"existing locked destination")
            existing = output.read_bytes()
            with patch(
                "ifc_context_repair.repair.os.replace",
                side_effect=PermissionError("simulated destination lock"),
            ):
                with self.assertRaises(PermissionError):
                    repair_file(RepairConfig(
                        source=source, output=output, overwrite_output=True
                    ))
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(output.read_bytes(), existing)

    def test_interrupted_verification_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.ifc"
            output = Path(folder) / "sample_repaired.ifc"
            self._fixture(source)
            before = source.read_bytes()
            with patch(
                "ifc_context_repair.repair.verify_targeted_output",
                side_effect=CancelledError("simulated interrupted verification"),
            ):
                with self.assertRaises(CancelledError):
                    repair_file(RepairConfig(source=source, output=output))
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(output.exists())

    def test_malformed_ifc_preserves_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "malformed.ifc"
            output = Path(folder) / "malformed_repaired.ifc"
            source.write_bytes(b"not an IFC file")
            before = source.read_bytes()
            with self.assertRaises(Exception):
                repair_file(RepairConfig(source=source, output=output))
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
