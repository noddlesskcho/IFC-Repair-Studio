# IFC Repair Studio 0.4.2

Version 0.4.2 hardens the large-IFC repair pipeline. Production output is now proven to
use one variable-length-safe STEP stream write, followed by exact target verification,
an unrelated-change audit and atomic installation. It adds real byte/throughput/ETA
progress, per-stage timings, safe cancellation and cleanup, disk/lock preflight checks,
optional psutil diagnostics with a native Windows fallback, resolver decision traces,
and separately timed PDF/HTML reporting.

On the supplied 652.9 MB sample, the optimized repair completed in 32.843 seconds versus
the 49.443-second v0.4 baseline. The sample still reports 2,552 slabs scanned, 2,051
affected slabs, 4,851 slab representations, 3,151 affected and repaired
representations, and zero targeted issues remaining.

See `docs/technical-audit-v0.4.2.md` for the full traced execution path, write-method
classification, benchmark evidence, safety proof, warning classification and known
limitations.

---

# IFC Repair Studio 0.4.1

Version 0.4.1 simplifies the desktop interface and redesigns reporting for professional
project submission and engineering review.

- Removed the desktop theme control and all Open Folder actions.
- Replaced completion actions with one compact Open Report menu for HTML, PDF and the
  repaired IFC.
- Replaced automatic PDF/JSON/CSV/LOG bundles with a five-page executive PDF and one
  complete, responsive, offline HTML engineering report.
- Added HTML search, filtering, sorting, pagination, copy actions, expandable evidence,
  light/dark display modes and filtered CSV/JSON exports.
- Debug logs are now opt-in through `--debug-logging` or `RepairConfig.debug_logging`.
- Separated report generation into PDF and HTML builders plus an explicit export service.

## Previous release: 0.4.0

Version 0.4.0 introduces an explicit workflow state machine, a rule-based repair shell,
safe Save As output by default, deterministic overwrite backups, structured stage
telemetry and JSON-lines diagnostics, manifest-based targeted verification, optional
full IFC validation, responsive elapsed/output-size reporting, expanded failure-safety
tests, and a multi-resolution Windows application icon.

The supplied 652.9 MB sample scans to the verified 2,552 / 2,051 / 4,851 / 3,151
element and representation counts. A warm scan measured 27.5 seconds, dominated by
23.1 seconds of native IfcOpenShell parsing. The first complete fast repair measured
49.4 seconds; its original full-output verification scan cost 10.5 seconds. The new
patch manifest reduces that verification operation to approximately 0.014 seconds on
the synthetic benchmark without broadening repair scope.

Previous release history follows.

Version 0.3.0 removes the non-functional navigation sidebar and uses a single-purpose
Select -> Scan -> Repair screen. The details section now uses independent columns so
long paths and labels cannot overlap. Detection and repair are restricted to direct
IfcSlab shape representations; other IFC product classes are ignored. Reports are now
generated as visually verified PDF files. On the supplied 652.9 MB sample, the targeted
scan parsed 4,851 slab representations and found 3,151 impacted representations, all
owned by IfcSlab. The targeted writer was also replaced with a memory-mapped patcher;
an 18.5 MB / 300,000-record benchmark improved to approximately 42.6 MiB/s while
preserving every non-target byte.

The previous dashboard and general-purpose behavior are documented below.

Built and verified on Windows 11 with Python 3.12.13, IfcOpenShell 0.8.5,
PySide6 6.11.1, and PyInstaller 6.21.0.

Verification completed:

- 15 automated tests pass when the private clean and faulty fixtures are configured,
  including real malformed IFC parse/diagnose/repair/write/reopen;
- streaming prescan exercised with 20,000 synthetic STEP records;
- quoted strings, doubled apostrophes, multiline records, whitespace, mixed case, and
  unrelated `$` values are covered;
- PySide6 window starts in offscreen smoke testing;
- packaged Windows executable reaches its GUI event loop.

Eight supplied clean IFC4 references from Revit 2024–2026 pass prescan and full
IfcOpenShell validation with zero issues. Their Body and FootPrint context patterns are
documented as positive evidence. Product tracing through `IfcShapeAspect` was corrected
from this inspection. Large-file profiling and CORENET X / IFC+SG external validation
remain required before production approval.

Four faulty linked-model exports were subsequently diagnosed. Version 0.1.2 adds the
clean-reference semantic profiles, fixes JSON report recursion, and verifies targeted
repairs for all 11 malformed representations. The four repaired proof-of-concept files
reopen with zero IfcOpenShell validation issues and pass affected-product geometry tests.

Version 0.1.3 simplifies the desktop UI to Select → Scan → Repair. Output is fixed to
the source folder, the validated repaired file keeps the original filename, and the
untouched original is atomically renamed with `_backup`. The completion screen shows
the file location, fixed count, unresolved count, and remaining validation issues.

Version 0.1.4 expands the scan summary with counts grouped by representation identifier
and type, such as Body / SweptSolid and FootPrint / Curve2D. “Safe to repair” is renamed
to “Ready for automatic repair” and explained directly in the summary; unresolved items
are labelled “Needs manual review” and remain unchanged.

Version 0.2.0 renames the application to IFC Repair Studio and introduces the dashboard
interface based on the approved reference design. Large-file work removes the duplicate
source parse during repair, caches the shape-representation query, makes the initial UI
scan skip full validation, hashing, and semantic snapshots, and adds cancellation between
native processing stages. Full before/after validation still runs during repair.
