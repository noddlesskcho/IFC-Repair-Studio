# IFC+SG Repair Assistant

IFC+SG Repair Assistant helps BIM users detect and repair a known
geometry-reference issue found in IFC+SG files exported from Autodesk Revit
2025 and Revit 2026.

The application restores missing IFC geometry references without changing the
model geometry, helping prepare the IFC for the next stage of CORENET X
submission.

## Production scope

- Schema: IFC4 only for repair; unsupported schemas receive a limited audit.
- Inputs: `.ifc`, `.ifczip`, or `.zip` containing exactly one IFC.
- Supported exporters: Autodesk Revit 2025 and Autodesk Revit 2026 IFC+SG.
- Modes: Audit Only and Repair IFC.
- Writer: one-pass, variable-length STEP patching to a same-directory temporary
  output, mandatory verification, then atomic installation.
- Reports: concise PDF and interactive offline HTML. JSON is optional.

Version 1 production repair:

- Direct `IfcProduct -> IfcProductDefinitionShape -> IfcShapeRepresentation`
- Body / SweptSolid
- Body / Tessellation
- FootPrint / Curve2D

Retained developer rules, skipped before detection in Version 1:

- `SHAPE_ASPECT_PRODUCT_MISSING_CONTEXT_V1`
- `SHAPE_ASPECT_MAP_MISSING_CONTEXT_V1`
- `REPRESENTATION_MAP_MISSING_CONTEXT_V1`
- `REPRESENTATION_MAP_FOOTPRINT_MISSING_CONTEXT_V1`

Report-only beta checks:

- `IFCSPACE_BODY_AUDIT_V1`
- `BASE_QUANTITY_AUDIT_V1`
- `IFCSG_GEOREFERENCING_AUDIT_V1`

## Development

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[ui,test,build,diagnostics]"
pytest
ifc-context-repair-gui
```

CLI examples:

```powershell
ifc-context-repair scan model.ifczip --mode audit --json
ifc-context-repair scan model.ifc --mode production
ifc-context-repair repair model.ifc --mode production --output model_repaired.ifc
```

Build:

```powershell
.\scripts\build_windows.ps1 -Python .\.venv\Scripts\python.exe
```

See:

- [Production architecture](docs/production-architecture-v1.0.md)
- [Version 1 direct-product scope](docs/version1-direct-product-scope.md)
- [User guide](docs/user-guide-v1.0.md)
- [Rule development guide](docs/ifc-sg-rule-development-guide.md)
- [Known limitations](docs/known-limitations-v1.0.md)
- [Build instructions](docs/build-v1.0.md)
- [Performance results](docs/benchmark-version1.md)
- [Release validation](docs/release-validation-v1.0.md)
- [PyInstaller warning classification](docs/pyinstaller-warning-classification-v1.0.md)

> This application performs targeted repairs for known IFC+SG export issues.
> It is not a complete IFC validator or CORENET X compliance checker. A
> repaired IFC should still undergo the normal submission validation process.
