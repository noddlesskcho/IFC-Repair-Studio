import importlib.util
import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.rules import ACTIVE_RULE


@unittest.skipUnless(importlib.util.find_spec("ifcopenshell"), "IfcOpenShell not installed")
class SlabRuleScopeTests(unittest.TestCase):
    def test_non_slab_ownership_paths_are_ignored(self):
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

        slab_rep = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=sub,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[item],
        )
        slab_shape = model.create_entity(
            "IfcProductDefinitionShape", Representations=[slab_rep]
        )
        model.create_entity(
            "IfcSlab", GlobalId=ifcopenshell.guid.new(), Representation=slab_shape
        )

        ignored_reps = []
        for entity_type in ("IfcWall", "IfcOpeningElement", "IfcRailing", "IfcCovering"):
            rep = model.create_entity(
                "IfcShapeRepresentation", ContextOfItems=sub,
                RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[item],
            )
            shape = model.create_entity(
                "IfcProductDefinitionShape", Representations=[rep]
            )
            model.create_entity(
                entity_type, GlobalId=ifcopenshell.guid.new(), Representation=shape
            )
            ignored_reps.append(rep.id())

        aspect_rep = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=sub,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[item],
        )
        model.create_entity(
            "IfcShapeAspect", ShapeRepresentations=[aspect_rep], Name="Ignored",
            ProductDefinitional=False,
        )
        mapped_rep = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=sub,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[item],
        )
        model.create_entity(
            "IfcRepresentationMap", MappingOrigin=axis, MappedRepresentation=mapped_rep
        )

        malformed_ids = [*ignored_reps, aspect_rep.id(), mapped_rep.id()]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scope.ifc"
            model.write(str(path))
            data = path.read_bytes()
            for step_id in malformed_ids:
                data = data.replace(
                    f"#{step_id}=IFCSHAPEREPRESENTATION(#{sub.id()},".encode(),
                    f"#{step_id}=IFCSHAPEREPRESENTATION($,".encode(), 1,
                )
            path.write_bytes(data)
            model = ifcopenshell.open(str(path))
            result = ACTIVE_RULE.detect(model)
        self.assertEqual(result.diagnoses, [])
        self.assertEqual(result.elements_scanned, 1)
        self.assertEqual(result.representations_scanned, 1)
        target_ids = {item.representation_step_id for item in result.targets}
        self.assertTrue(target_ids.isdisjoint(ignored_reps))
        self.assertNotIn(aspect_rep.id(), target_ids)
        self.assertNotIn(mapped_rep.id(), target_ids)


if __name__ == "__main__":
    unittest.main()
