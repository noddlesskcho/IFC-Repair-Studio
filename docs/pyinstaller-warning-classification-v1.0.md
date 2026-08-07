# PyInstaller warning classification — v1.0.0

Build warning source:
`build-final/IFCSGRepairAssistant-1.0.0/warn-IFCSGRepairAssistant-1.0.0.txt`

Warnings are classified from their import sites and checked against the source
test suite, a 622.6 MB end-to-end regression, and a packaged self-test.

| Category | Examples | Classification | Action |
|---|---|---|---|
| Non-Windows platform modules | `pwd`, `grp`, `fcntl`, `termios`, `posix`, `resource`, `_scproxy` | Expected platform-specific | None |
| PyInstaller bootstrap aliases | `pyimod02_importers`, selected `multiprocessing.*` names | False positive | None |
| Optional Lark features | `rich`, `pydot`, `regex`, `interegular`, `atomicwrites` | Optional dependency | Not used by the production IFC path |
| Optional IfcOpenShell tooling | `simple_spf`, `express_parser`, `schema_class`, `codegen`, `_pytest` | Development or optional tooling | Keep excluded |
| NumPy generated symbols | `numpy._core.*` scalar and ufunc names | False positive from dynamic exports | No action |
| Cross-runtime probes | `java`, `java.lang`, `vms_lib`, `_winreg` | Expected conditional imports | None |
| Optional diagnostics | `psutil` | Optional dependency | Bundle when installed; diagnostics degrade gracefully |
| ReportLab dynamic exports | `XPreformatted`, `cleanBlockQuotedText`, `reportlab_mods` | False positive or optional extension | PDF generation is exercised end to end |
| Required runtime | PySide6, Pillow, ReportLab, IfcOpenShell | No unresolved required-module warning | Bundled and exercised by the packaged self-test |

No warning is suppressed merely to reduce the warning count. OCC/3D rendering,
pytest and developer-only tooling remain outside the frozen runtime because the
Version 1 application does not use them.

## Validation

The v1.0.0 workflow verified:

- direct-product Body / SweptSolid, Body / Tessellation and FootPrint / Curve2D;
- disabled ShapeAspect and RepresentationMap rules skipped before detection;
- variable-length targeted STEP patching;
- targeted verification and semantic reopen verification;
- zero unexpected changed records;
- independent PDF and HTML report generation.

The packaged self-test exercises the frozen IfcOpenShell, patch writer,
verification and report stack. This evidence is more useful than hiding optional
warnings simply to make the warning file empty.
