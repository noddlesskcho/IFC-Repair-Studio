import importlib.util
import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.rules import ACTIVE_RULE


@unittest.skipUnless(importlib.util.find_spec("ifcopenshell"), "IfcOpenShell not installed")
class ProductRuleScopeTests(unittest.TestCase):
    def test_version1_collects_only_supported_direct_product_contexts(self):
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

        supported_reps = []
        host_wall = None
        hosted_opening = None
        for entity_type in ("IfcWall", "IfcOpeningElement", "IfcRailing", "IfcCovering"):
            rep = model.create_entity(
                "IfcShapeRepresentation", ContextOfItems=sub,
                RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[item],
            )
            shape = model.create_entity(
                "IfcProductDefinitionShape", Representations=[rep]
            )
            product = model.create_entity(
                entity_type, GlobalId=ifcopenshell.guid.new(), Representation=shape
            )
            if entity_type == "IfcWall":
                host_wall = product
            elif entity_type == "IfcOpeningElement":
                hosted_opening = product
            supported_reps.append(rep.id())
        model.create_entity(
            "IfcRelVoidsElement", GlobalId=ifcopenshell.guid.new(),
            RelatingBuildingElement=host_wall, RelatedOpeningElement=hosted_opening,
        )
        orphan_rep = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=sub,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid",
            Items=[item],
        )
        orphan_shape = model.create_entity(
            "IfcProductDefinitionShape", Representations=[orphan_rep]
        )
        model.create_entity(
            "IfcOpeningElement", GlobalId=ifcopenshell.guid.new(),
            Representation=orphan_shape,
        )

        unsupported_rep = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=sub,
            RepresentationIdentifier="Clearance", RepresentationType="BoundingBox",
            Items=[item],
        )
        unsupported_shape = model.create_entity(
            "IfcProductDefinitionShape", Representations=[unsupported_rep]
        )
        model.create_entity(
            "IfcWall", GlobalId=ifcopenshell.guid.new(),
            Representation=unsupported_shape,
        )

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

        malformed_ids = [
            *supported_reps, orphan_rep.id(), unsupported_rep.id(),
            aspect_rep.id(), mapped_rep.id(),
        ]
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
        expected_direct = {*supported_reps, orphan_rep.id()}
        self.assertEqual(
            {item.representation_step_id for item in result.diagnoses},
            expected_direct,
        )
        self.assertEqual(result.elements_scanned, 7)
        self.assertEqual(result.representations_scanned, 7)
        target_ids = {item.representation_step_id for item in result.targets}
        self.assertEqual(target_ids, expected_direct)
        orphan_target = next(
            item for item in result.targets
            if item.representation_step_id == orphan_rep.id()
        )
        self.assertFalse(orphan_target.automatically_repairable)
        self.assertNotIn(unsupported_rep.id(), target_ids)
        self.assertNotIn(aspect_rep.id(), target_ids)
        self.assertNotIn(mapped_rep.id(), target_ids)


if __name__ == "__main__":
    unittest.main()
