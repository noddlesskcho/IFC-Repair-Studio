from __future__ import annotations

from pathlib import Path
from typing import Any


def build_ifc_sg_fixture(
    path: Path,
    *,
    direct_missing: bool = False,
    shape_aspect_missing: bool = False,
    map_missing: bool = False,
    footprint_map_missing: bool = False,
    type_owned_without_occurrences: bool = False,
    space_without_body: bool = False,
    quantity_review: bool = False,
    georeferencing: bool = False,
) -> dict[str, Any]:
    """Build a compact IFC4 semantic fixture and return its important entities."""
    import ifcopenshell

    model = ifcopenshell.file(schema="IFC4")
    point = model.create_entity(
        "IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)
    )
    axis = model.create_entity("IfcAxis2Placement3D", Location=point)
    root = model.create_entity(
        "IfcGeometricRepresentationContext",
        ContextIdentifier="Model",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=axis,
    )
    project = model.create_entity(
        "IfcProject",
        GlobalId=ifcopenshell.guid.new(),
        Name="Synthetic IFC+SG Project",
        RepresentationContexts=[root],
    )
    body_context = model.create_entity(
        "IfcGeometricRepresentationSubContext",
        ContextIdentifier="Body",
        ContextType="Model",
        ParentContext=root,
        TargetView="MODEL_VIEW",
    )
    footprint_context = model.create_entity(
        "IfcGeometricRepresentationSubContext",
        ContextIdentifier="FootPrint",
        ContextType="Model",
        ParentContext=root,
        TargetView="MODEL_VIEW",
    )
    item = model.create_entity(
        "IfcBoundingBox", Corner=point, XDim=1.0, YDim=1.0, ZDim=1.0
    )
    direct = model.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body_context,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=[item],
    )
    pds = model.create_entity("IfcProductDefinitionShape", Representations=[direct])
    wall = model.create_entity(
        "IfcWall",
        GlobalId=ifcopenshell.guid.new(),
        Name="Synthetic wall",
        Representation=pds,
    )
    peer_rep = model.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body_context,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=[item],
    )
    peer_footprint = model.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=footprint_context,
        RepresentationIdentifier="FootPrint",
        RepresentationType="Curve2D",
        Items=[item],
    )
    peer_pds = model.create_entity(
        "IfcProductDefinitionShape", Representations=[peer_rep, peer_footprint]
    )
    model.create_entity(
        "IfcSlab",
        GlobalId=ifcopenshell.guid.new(),
        Name="Valid semantic peer",
        Representation=peer_pds,
    )

    result: dict[str, Any] = {
        "model": model,
        "project": project,
        "direct": direct,
        "wall": wall,
        "body_context": body_context,
        "footprint_context": footprint_context,
    }
    mutation_ids: list[int] = []
    if direct_missing:
        mutation_ids.append(direct.id())
    if shape_aspect_missing:
        aspect_rep = model.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=body_context,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[item],
        )
        model.create_entity(
            "IfcShapeAspect",
            ShapeRepresentations=[aspect_rep],
            Name="Synthetic aspect",
            ProductDefinitional=True,
            PartOfProductDefinitionShape=pds,
        )
        mutation_ids.append(aspect_rep.id())
        result["shape_aspect_rep"] = aspect_rep
    if map_missing or footprint_map_missing:
        identifier = "FootPrint" if footprint_map_missing else "Body"
        representation_type = "Curve2D" if footprint_map_missing else "SweptSolid"
        context = footprint_context if footprint_map_missing else body_context
        mapped_rep = model.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=context,
            RepresentationIdentifier=identifier,
            RepresentationType=representation_type,
            Items=[item],
        )
        representation_map = model.create_entity(
            "IfcRepresentationMap",
            MappingOrigin=axis,
            MappedRepresentation=mapped_rep,
        )
        if type_owned_without_occurrences or footprint_map_missing:
            mapped_body = model.create_entity(
                "IfcShapeRepresentation",
                ContextOfItems=body_context,
                RepresentationIdentifier="Body",
                RepresentationType="SweptSolid",
                Items=[item],
            )
            sibling_map = model.create_entity(
                "IfcRepresentationMap",
                MappingOrigin=axis,
                MappedRepresentation=mapped_body,
            )
            model.create_entity(
                "IfcPlateType",
                GlobalId=ifcopenshell.guid.new(),
                Name="Synthetic plate type",
                RepresentationMaps=[sibling_map, representation_map],
                PredefinedType="CURTAIN_PANEL",
            )
        mutation_ids.append(mapped_rep.id())
        result["mapped_rep"] = mapped_rep
        result["representation_map"] = representation_map
    if space_without_body:
        result["space"] = model.create_entity(
            "IfcSpace",
            GlobalId=ifcopenshell.guid.new(),
            Name="Synthetic space without Body",
        )
    if quantity_review:
        result["quantity"] = model.create_entity(
            "IfcElementQuantity",
            GlobalId=ifcopenshell.guid.new(),
            Name="Qto_WallBaseQuantities",
            MethodOfMeasurement=None,
            Quantities=[],
        )
    if georeferencing:
        crs = model.create_entity("IfcProjectedCRS", Name="SVY21")
        conversion = model.create_entity(
            "IfcMapConversion",
            SourceCRS=root,
            TargetCRS=crs,
            Eastings=28001.0,
            Northings=38744.0,
            OrthogonalHeight=100.0,
            XAxisAbscissa=1.0,
            XAxisOrdinate=0.0,
            Scale=1.0,
        )
        result.update({"projected_crs": crs, "map_conversion": conversion})

    model.write(str(path))
    if mutation_ids:
        data = path.read_bytes()
        for representation_id in mutation_ids:
            marker = f"#{representation_id}=IFCSHAPEREPRESENTATION(".encode()
            start = data.find(marker)
            if start < 0:
                raise AssertionError(f"Representation #{representation_id} not serialized")
            token = start + len(marker)
            end = data.find(b",", token)
            data = data[:token] + b"$" + data[end:]
        path.write_bytes(data)
    return result
