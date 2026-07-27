# PyInstaller warning classification — v1.0.0

Build warning source:
`build/IFCSGRepairAssistant-1.0.0/warn-IFCSGRepairAssistant-1.0.0.txt`

The final build contains 250 missing/excluded-module warning lines. The count is
inflated by NumPy's generated public symbols. Warnings were classified from
their import sites and then checked against the packaged end-to-end test.

| Category | Examples | Classification | Action |
|---|---|---|---|
| Non-Windows platform modules | `pwd`, `grp`, `fcntl`, `termios`, `posix`, `resource`, `_scproxy` | Expected platform-specific | None |
| PyInstaller bootstrap aliases | `pyimod02_importers`, selected `multiprocessing.*` names | False positive | None |
| Optional Lark features | `rich`, `pydot`, `regex`, `interegular`, `atomicwrites` | Optional dependency | None; not used by the production IFC path |
| Optional IfcOpenShell tooling | `mvd_info`, `express_parser`, `schema_class`, `codegen`, `_pytest` | Development or optional tooling | Keep excluded; production semantic loading and repair are packaged and tested |
| NumPy generated symbols | `numpy._core.*` scalar and ufunc names | False positive from dynamic exports | None; packaged NumPy imports successfully |
| Cross-runtime probes | `java`, `java.lang`, `vms_lib`, `_winreg` | Expected conditional imports | None |
| Optional diagnostics | `psutil` | Optional dependency | Spec includes it automatically when installed; Windows diagnostics fallback remains active |
| Required UI/reporting/runtime | PySide6, ReportLab, Pillow, IfcOpenShell | No unresolved required-module warning | Bundled and exercised by packaged self-test |

No warning was suppressed merely to reduce the count. OCC/3D geometry rendering,
pytest, and developer tooling remain outside the runtime because the application
does not use them in its normal production path.

## Packaged validation

The windowed v1.0.0 executable completed an end-to-end diagnostic run using a
synthetic IFC4 IFC+SG fixture:

- semantic IFC load completed;
- direct and type-owned representation-map rules executed;
- two variable-length STEP repairs were written through the streaming patcher;
- targeted verification passed;
- unexpected changed records: zero;
- three report-only audit findings were produced;
- PDF and HTML reports were generated;
- process exit code: zero.

This validation is stronger evidence than an empty warning file: it exercises
the modules the production workflow actually imports.
