# IFC Repair Studio

A Windows desktop and command-line utility that detects, explains, repairs, and
revalidates missing `IfcShapeRepresentation.ContextOfItems` references. It never
uses a fixed STEP ID, never replaces arbitrary `$` values, and never overwrites
the source by default.

## Status

The engine, CLI, state-driven desktop UI, versioned slab rule, deterministic resolver,
manifest-verified atomic repair, optional debug diagnostics, concise PDF executive reports,
interactive offline HTML engineering reports, comparison
tools, and failure-safety tests are implemented. External CORENET X testing remains a
separate acceptance step.

## Install on Windows

Install 64-bit Python 3.11 or 3.12, then from PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[ui,test]"
pytest
ifc-context-repair-gui
```

IfcOpenShell is deliberately a required runtime dependency. The prescan and its
tests can run without it; semantic diagnosis and repair cannot.

## CLI

```powershell
ifc-context-repair scan model.ifc --json
ifc-context-repair validate model.ifc --json
ifc-context-repair repair model.ifc --output model_repaired.ifc --report report.pdf
ifc-context-repair compare clean.ifc faulty.ifc --output comparison.json
ifc-context-repair benchmark model.ifc
```

Exit codes are `0` success, `1` affected/no repair, `2` validation failure,
`3` ambiguous, `4` input/parse error, `5` output/write error, and `6` unexpected.

## Safety model

Only semantic `IfcShapeRepresentation` candidates are considered. Automatic
repair is limited to **Safe to repair** decisions. Warning-level decisions need
an explicit option; ambiguous and unrepairable cases are never changed. Output is
written once to a same-volume temporary file, verified against an exact repair
manifest, and atomically installed. Full IFC validation is optional.
See [docs/architecture.md](docs/architecture.md) and [docs/user-guide.md](docs/user-guide.md).

The desktop UI uses a clear Select File -> Scan -> Repair and Verify workflow. The
recommended default writes `<name>_repaired.ifc` and never renames the original.
Advanced overwrite mode creates `<name>.original.ifc` (or a timestamped variant),
shows the exact paths, and requires explicit confirmation.
