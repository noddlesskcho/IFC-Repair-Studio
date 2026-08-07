import importlib.util
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("ifcopenshell"), "IfcOpenShell not installed")
class IfcOpenShellRoundTripTests(unittest.TestCase):
    def test_synthetic_missing_context_can_be_diagnosed(self):
        import ifcopenshell
        from ifc_context_repair.detector import diagnose_model
        from ifc_context_repair.config import RepairConfig
        from ifc_context_repair.parser import open_model
        from ifc_context_repair.repair import repair_file
        from ifc_context_repair.repair import analyse

        model = ifcopenshell.file(schema="IFC4")
        point = model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
        axis = model.create_entity("IfcAxis2Placement3D", Location=point)
        context = model.create_entity("IfcGeometricRepresentationContext", ContextIdentifier="Model",
                                      ContextType="Model", CoordinateSpaceDimension=3,
                                      Precision=1e-5, WorldCoordinateSystem=axis)
        project = model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(),
                                      RepresentationContexts=[context])
        sub = model.create_entity("IfcGeometricRepresentationSubContext", ContextIdentifier="Body",
                                  ContextType="Model", ParentContext=context,
                                  TargetView="MODEL_VIEW")
        item = model.create_entity("IfcBoundingBox", Corner=point, XDim=1.0, YDim=1.0, ZDim=1.0)
        valid = model.create_entity("IfcShapeRepresentation", ContextOfItems=sub,
                                    RepresentationIdentifier="Body", RepresentationType="SweptSolid",
                                    Items=[item])
        invalid = model.create_entity("IfcShapeRepresentation", ContextOfItems=sub,
                                      RepresentationIdentifier="Body", RepresentationType="SweptSolid",
                                      Items=[item])
        shape = model.create_entity("IfcProductDefinitionShape", Representations=[valid, invalid])
        slab = model.create_entity("IfcSlab", GlobalId=ifcopenshell.guid.new(), Representation=shape)
        wall_invalid = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=sub,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[item],
        )
        wall_shape = model.create_entity(
            "IfcProductDefinitionShape", Representations=[wall_invalid]
        )
        model.create_entity(
            "IfcWall", GlobalId=ifcopenshell.guid.new(), Representation=wall_shape
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "malformed.ifc"
            repaired = Path(folder) / "repaired.ifc"
            model.write(str(path))
            original = path.read_bytes()
            target = (f"#{invalid.id()}=IFCSHAPEREPRESENTATION(#{sub.id()},".encode("ascii"))
            malformed = (f"#{invalid.id()}=IFCSHAPEREPRESENTATION($,".encode("ascii"))
            wall_target = (
                f"#{wall_invalid.id()}=IFCSHAPEREPRESENTATION(#{sub.id()},".encode("ascii")
            )
            wall_malformed = (
                f"#{wall_invalid.id()}=IFCSHAPEREPRESENTATION($,".encode("ascii")
            )
            self.assertIn(target, original)
            self.assertIn(wall_target, original)
            path.write_bytes(
                original.replace(target, malformed, 1).replace(
                    wall_target, wall_malformed, 1
                )
            )
            opened = open_model(path)
            quick_report = analyse(path, validate=False, quick=True)
            self.assertIsNone(quick_report.snapshot_before)
            self.assertEqual(quick_report.validation_before, [])
            self.assertEqual(quick_report.summary_counts["RepresentationsScanned"], 3)
            self.assertEqual(quick_report.summary_counts["AffectedRepresentations"], 2)
            self.assertEqual(
                quick_report.element_type_counts["IfcWall"]["affected_representations"], 1
            )
            diagnoses, _ = diagnose_model(opened)
            self.assertEqual(len(diagnoses), 1)
            self.assertEqual(diagnoses[0].proposed_context.step_id, sub.id())
            self.assertEqual(diagnoses[0].product_class, "IfcSlab")
            self.assertEqual(diagnoses[0].product_global_id, slab.GlobalId)
            opened.by_id(invalid.id()).ContextOfItems = opened.by_id(sub.id())
            opened.write(str(repaired))
            reopened = open_model(repaired)
            self.assertEqual(reopened.by_id(invalid.id()).ContextOfItems.id(), sub.id())
            semantic_output = Path(folder) / "pipeline_repaired.ifc"
            with patch("ifc_context_repair.repair.open_model", wraps=open_model) as mocked_open:
                report = repair_file(RepairConfig(source=path, output=semantic_output,
                                                  create_backup=False))
                # Production verification now mandates one source open and one
                # repaired-output reopen with entity-count comparison.
                self.assertEqual(mocked_open.call_count, 2)
            self.assertEqual(report.output, str(semantic_output.resolve()))
            self.assertEqual(len(report.diagnoses), 2)
            self.assertTrue(all(item.repaired for item in report.diagnoses))
            self.assertTrue(report.targeted_verification["passed"])
            self.assertIn("apply_patches", report.durations)
            self.assertIn("flush_output", report.durations)
            self.assertIn("targeted_verification", report.durations)
            self.assertTrue(report.change_audit["passed"])
            self.assertEqual(report.change_audit["unexpected_modified_records"], 0)
            self.assertIsNone(report.log_path)
            self.assertFalse((Path(folder) / "malformed_repair_debug.log").exists())
            debug_output = Path(folder) / "debug_repaired.ifc"
            debug_report = repair_file(RepairConfig(
                source=path, output=debug_output, debug_logging=True,
            ))
            self.assertTrue(Path(debug_report.log_path).is_file())
            self.assertEqual(open_model(semantic_output).by_id(invalid.id()).ContextOfItems.id(),
                             sub.id())
            self.assertEqual(
                open_model(semantic_output).by_id(wall_invalid.id()).ContextOfItems.id(),
                sub.id(),
            )
            replace_source = Path(folder) / "replace_in_place.ifc"
            replace_source.write_bytes(path.read_bytes())
            original_bytes = replace_source.read_bytes()
            replace_report = repair_file(RepairConfig(
                source=replace_source, create_backup=True, repair_mode="targeted",
                replace_original_with_backup=True,
            ))
            backup = Path(replace_report.backup)
            self.assertEqual(backup.name, "replace_in_place.original.ifc")
            self.assertEqual(backup.read_bytes(), original_bytes)
            self.assertEqual(open_model(replace_source).by_id(invalid.id()).ContextOfItems.id(),
                             sub.id())
            self.assertEqual(
                open_model(replace_source).by_id(wall_invalid.id()).ContextOfItems.id(),
                sub.id(),
            )


if __name__ == "__main__":
    unittest.main()
