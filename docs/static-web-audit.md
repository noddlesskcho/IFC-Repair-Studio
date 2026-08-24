# Static web conversion audit

## Executive finding

The original application is a native Python desktop program, not a web
application. It has no HTTP backend and no existing browser frontend. GitHub
Pages cannot execute its Python, Qt, IfcOpenShell, ReportLab, filesystem, thread,
or PyInstaller code. The conversion therefore retains the desktop application
and adds a separate static Browser Edition implementing the proven, targeted
STEP-repair subset with browser-native APIs.

## Existing architecture before conversion

| Area | Finding |
| --- | --- |
| Framework | Python 3.11-3.13 and PySide6/Qt desktop UI |
| GUI entry point | `src/ifc_context_repair/app.py:main` via `ifc-context-repair-gui` |
| CLI entry point | `src/ifc_context_repair/cli.py:main` via `ifc-context-repair` |
| Main UI | `src/ifc_context_repair/ui/main_window.py:MainWindow` |
| Job execution | Qt worker objects, `QThread`, queued signals/slots |
| Core dependencies | IfcOpenShell 0.8, ReportLab 4.4; optional PySide6, psutil, pytest, PyInstaller |
| Node dependencies | None before this conversion |
| API endpoints | None |
| Backend server | None |
| Packaging | PyInstaller Windows executable |

## Execution and filesystem assumptions

The desktop path accepts `.ifc`, `.ifczip`, or a ZIP containing one IFC through
`file_io.prepare_input()`. It extracts archives to a temporary directory, uses
`Path` and normal filesystem permissions, writes a same-directory temporary IFC,
flushes it, verifies it, atomically installs the final output, and writes PDF,
HTML, JSON, and diagnostic files. It can query free disk, locks, process memory,
and local paths. Those operations are not available to a GitHub Pages document.

The desktop semantic path opens the model with `ifcopenshell.open()` through
`parser.open_ifc()`. `repair.analyse()` and `repair.repair_file()` run prescan,
semantic context/ownership resolution, patch planning, output streaming, target
verification, change audit, optional full validation, and reports. The normal
repair writer already avoids `ifcopenshell.file.write()` and applies ordered,
variable-length STEP patches to a new output.

## Processing-function classification

| Existing capability | Class | Browser implementation / disposition |
| --- | --- | --- |
| Select an IFC | A - direct JavaScript | `<input type=file>` and drag/drop |
| Read large uncompressed IFC | A | `File.stream()` byte scanner with progress |
| Inspect STEP entity IDs/types | A | Browser STEP record scanner |
| Detect FILE_SCHEMA/header/footer | A | Header/footer byte slices and regex |
| Split nested STEP arguments | A | Quote/comment/parenthesis-aware parser |
| Build direct PDS ownership | A | Compact STEP-ID maps in `ifc-analyzer.js` |
| Resolve project-connected contexts | C - replacement | Narrow semantic resolver matching desktop evidence policy |
| Patch `$` to variable-length `#id` | A | Original `Blob.slice()` segments plus encoded token |
| Download repaired IFC | A | `Blob`, object URL, temporary download anchor |
| Target/change verification | C | Record-level before/after verification in JavaScript |
| IfcOpenShell semantic load | B in theory | No audited browser WASM distribution is bundled; kept desktop-only |
| Full IFC schema validation | B/D | Desktop-only until a tested browser schema engine is approved |
| Geometry engine / rendering checks | B/D | Desktop-only |
| ShapeAspect/map ownership rules | C | Existing code retained on desktop; not silently approximated in browser |
| ZIP/IFCZIP extraction | A/C | Not in initial browser scope; uncompressed IFC is required |
| PDF/engineering HTML reports | C | Desktop-only in initial Browser Edition |
| Disk, locks, atomic rename, psutil | D | Browser sandbox has no equivalent; output is downloaded explicitly |
| Native application shutdown/cancel | D/C | Replaced by cooperative event-loop yields and browser lifecycle |

Classes: **A** runs directly in JavaScript; **B** would require WebAssembly;
**C** requires a deliberate browser replacement; **D** cannot reasonably retain
the same native semantics on a static site.

## Features already client-side before conversion

None. PySide6 renders locally on a user's computer, but it is not browser-side
code and cannot be served by GitHub Pages.

## GitHub Pages blockers identified

- Python and native IfcOpenShell cannot execute on GitHub Pages.
- PySide6 requires a native Qt process and filesystem dialogs.
- ReportLab and PDF generation are Python-only in the current implementation.
- Native temporary files, `os.replace`, `fsync`, file locks, free-disk probes,
  and rotating logs are unavailable to a static page.
- QThread workers and Qt signals do not exist in a browser.
- `.ifczip` extraction was implemented with Python archive APIs.
- Full IfcOpenShell re-open validation cannot be claimed by a JavaScript parser.
- Absolute or root-relative asset URLs would break under a repository path.

## Resulting static architecture

```text
index.html
css/app.css
js/app.js
js/ui.js
js/ifc-loader.js
js/ifc-analyzer.js
js/ifc-fixer.js
js/ifc-exporter.js
wasm/
vendor/
tests/browser/
.github/workflows/deploy-pages.yml
```

There is no router, API, service worker, external CDN, telemetry endpoint, or
runtime package install. All asset references use `./` repository-relative
paths. Development uses Node only for tests and allow-list staging; the deployed
files are plain static HTML/CSS/JavaScript.

## Safety boundary

The Browser Edition does not pretend that its lightweight STEP parser is
IfcOpenShell. It repairs only direct IFC4 Body/SweptSolid and FootPrint/Curve2D
records when the target is missing, one project-connected compatible context
exists, strong sibling, same-file peer, or validated slab-pattern evidence
exists, and no conflict is found. Experimental signatures are visible as
report-only. Indirect geometry,
schema validation, geometry generation, and rich reports remain explicitly
available only in the desktop product.
