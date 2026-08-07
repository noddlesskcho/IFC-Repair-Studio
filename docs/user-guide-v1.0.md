# User Guide — IFC+SG Repair Assistant 1.0

IFC+SG Repair Assistant helps BIM users detect and repair a known
geometry-reference issue found in IFC+SG files exported from Autodesk Revit
2025 and Revit 2026.

The application restores missing IFC geometry references without changing the
model geometry, helping prepare the IFC for the next stage of CORENET X
submission.

## Supported workflow

- Autodesk Revit 2025 IFC+SG
- Autodesk Revit 2026 IFC+SG
- IFC4
- CORENET X pre-submission preparation
- `.ifc`, `.ifczip`, or `.zip` containing exactly one IFC

## Workflow

1. Select an IFC.
2. Choose **Repair IFC** or **Audit Only**.
3. Select **Check IFC**.
4. Review:
   - Geometry References Found
   - Ready to Repair
   - Items Remaining
   - IFC Verification
5. If repair is available, select **Repair IFC**.
6. Open the repaired IFC or Detailed Report.

### Audit Only

Checks the IFC and generates a report without changing the file.

### Repair IFC

Repairs supported Body / SweptSolid, Body / Tessellation and FootPrint / Curve2D
geometry references directly owned by products, then verifies the repaired IFC.
The original IFC remains unchanged. ShapeAspect and RepresentationMap geometry
references are outside the Version 1 scope and are not scanned or modified.

## Unsupported files

IFC2X3, IFC4X3, non-Revit exporters, and files where Revit 2025 or 2026 cannot
be identified receive audit results only. Automatic repair is disabled.

## Important note

This application performs targeted repairs for known IFC+SG export issues.

It is not a complete IFC validator or CORENET X compliance checker.

A repaired IFC should still undergo the normal submission validation process.
