# Indirect representation-context analysis — v0.6.0

## Retained repaired sample

Input: `validation-output/sample-large-v050-repaired.ifc`

- IFC size: 652,913,311 bytes
- IFC schema: IFC4
- Products indexed: 78,789
- Shape representations indexed: 142,504
- Missing `ContextOfItems` values classified: 20,378
- Index construction: 4.994 seconds after IFC parsing
- Classification: 1.938 seconds

## Classification result

| Classification | Signature | Count | HIGH | Ambiguous | Orphaned | Proposed action |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| ShapeAspect under product | Body / SweptSolid | 6,852 | 6,852 | 0 | 0 | Extended Repair |
| ShapeAspect under product | Body / Tessellation | 232 | 232 | 0 | 0 | Extended Repair |
| ShapeAspect under RepresentationMap | Body / SweptSolid | 7,077 | 7,077 | 0 | 0 | Extended Repair |
| ShapeAspect under RepresentationMap | Body / Tessellation | 6,201 | 6,201 | 0 | 0 | Extended Repair |
| RepresentationMap | FootPrint / Curve2D | 16 | 0 | 0 | 0 | Report only |
| **Total** |  | **20,378** | **20,362** | **0** | **0** |  |

All 20,362 HIGH-confidence cases resolve semantically to the file's project-connected
Body context (STEP `#26` in this sample only). The implementation does not hard-code
that ID; it is discovered from the current file.

The 16 `REPRESENTATION_MAP` FootPrint cases have zero reachable map usages and
therefore no outer representation context evidence. They remain LOW confidence with
no proposed context and are not repaired.

## Ultimate product impact

| Classification | Ultimate product class | Reachable usages/products |
| --- | --- | ---: |
| ShapeAspect under product | IfcWall | 6,828 |
| ShapeAspect under product | IfcRailing | 256 |
| ShapeAspect under RepresentationMap | IfcDoor | 8,579 |
| ShapeAspect under RepresentationMap | IfcWindow | 4,752 |
| ShapeAspect under RepresentationMap | IfcSanitaryTerminal | 2,550 |
| ShapeAspect under RepresentationMap | IfcFurniture | 584 |

Mapped shape-aspect records have between 1 and 6 usages (average 1.24). Product-impact
counts can exceed representation counts because one reusable representation can reach
multiple products.

## Safety conclusion

- Safe Repair makes no change to these indirect cases.
- Extended Repair changed 20,362 records and left 16 unchanged in
  `sample-large-v060-extended-repaired.ifc`.
- Audit Only makes no IFC change.
- Every proposed edit changes only the first `ContextOfItems` token.
- Target verification and the unrelated-record byte audit remain mandatory before
  atomic installation.

The completed Extended Repair verified 20,362 of 20,362 intended changes, reported
20,362 expected and actual modified STEP records, and found zero unexpected modified
records. The source file retained its original size and modification timestamp.
