# IFC+SG Repair Assistant 1.0.0

The production application is repositioned specifically for Autodesk Revit 2025
and Revit 2026 IFC+SG exports before CORENET X submission.

The modeller interface now uses a three-step workflow—Select IFC, Review Results,
Repair IFC—and only two modes: Audit Only and Repair IFC. Engineering
classifications, STEP identifiers, confidence evidence, relationship terminology,
processing strategy, and raw entity statistics have moved to the Detailed Report.

The final maintenance build separates the no-file and ready-to-review workflow
states. After selecting an IFC, the interface now advances to Review Results and
shows a visible **Review IFC** primary action.

Automatic repair is disabled for unsupported schemas, non-Revit exporters, and
files where Revit 2025 or 2026 cannot be identified. The repair algorithms,
streaming STEP writer, mandatory verification, and original-file protections are
unchanged.

---

# IFC Repair Studio 0.6.0

Version 0.6.0 adds a reusable representation-ownership index and classifies every
missing `IfcShapeRepresentation.ContextOfItems` as Direct Product, Shape Aspect under
a product, Shape Aspect under a representation map, Representation Map, Orphaned,
Ambiguous, or Unsupported. Safe Repair remains the default. Extended Repair changes
only HIGH-confidence indirect cases; Audit Only writes reports without changing an IFC.

The repaired 652.9 MB sample contains exactly 20,378 remaining missing contexts:
7,084 shape-aspect product representations, 13,278 shape-aspect map representations,
and 16 reusable FootPrint representation maps. The first 20,362 have unique
high-confidence contexts. The 16 map cases remain report-only because map usage does
not prove a compatible FootPrint context.

The UI now displays a visible animated progress bar during native parsing and real
determinate progress during indexing, classification, patch planning, byte streaming,
verification, and report generation. HTML report outcome alignment is corrected and
the report now includes classification, direct-product, shape-aspect, representation
map, ambiguous-case, verification, and diagnostics navigation.

---

# IFC Repair Studio 0.5.1

Version 0.5.1 fixes a packaged-Windows first-scan hang that could also open a second
application window. The PyInstaller entry point now calls
`multiprocessing.freeze_support()` before application startup, and a Windows named
mutex prevents accidental duplicate GUI instances. Scan telemetry now exposes context
index construction and opening-host relationship checks instead of leaving the last
collection count on screen.

The exact 652.9 MB `Sample Project.ifc` completes the source Qt worker workflow in
approximately 50 seconds and reports 8,926 safe representation repairs. The repair
rules and output transaction are unchanged from v0.5.0.

---

# IFC Repair Studio 0.5.0

Version 0.5.0 expands the proven slab repair into separately constrained policies for
`IfcWall`, `IfcOpeningElement`, `IfcRailing`, and `IfcCovering`. The UI still exposes
one **Repair All Safe Issues** action, while every representation is resolved and
verified independently and all accepted edits share one atomic STEP stream write.

Same-file exact representation semantics provide cross-product context evidence.
Ambiguous or identifier-only decisions remain excluded, indirect representation maps
and shape aspects remain out of scope, and openings must participate in
`IfcRelVoidsElement`. Scan results, PDF, HTML, and diagnostics now include per-element
counts.

On the retained 652.9 MB slab-repaired sample, v0.5.0 identifies 5,738 safe opening
Body repairs and 37 safe covering FootPrint repairs. The sample's slabs, walls, and
railings are already valid. The original v0.4.2 slab counts remain available as a
per-policy regression baseline.

---

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
# IFC Repair Studio 0.7.0 development foundation

Production IFC+SG / CORENET X pre-submission release.

## Product and workflow

- Positions the application as a specialised IFC+SG technical audit and repair
  tool, not a universal validator or compliance guarantee.
- Supports `.ifc`, `.ifczip`, and `.zip` containing exactly one IFC.
- Restricts automatic repairs to IFC4.
- Adds the internal audit and repair capabilities later presented through the
  simplified Audit Only and Repair IFC interface.
- Removes source-file replacement from the production UI and CLI.

## Rule engine

- Adds the registry-based `rules/ifc_sg` architecture and versioned metadata.
- Production rules:
  - `DIRECT_PRODUCT_MISSING_CONTEXT_V2`
  - `SHAPE_ASPECT_PRODUCT_MISSING_CONTEXT_V1`
  - `REPRESENTATION_MAP_MISSING_CONTEXT_V1`
  - `REPRESENTATION_MAP_FOOTPRINT_MISSING_CONTEXT_V1`
- Beta report-only rules:
  - `IFCSPACE_BODY_AUDIT_V1`
  - `BASE_QUANTITY_AUDIT_V1`
  - `IFCSG_GEOREFERENCING_AUDIT_V1`
- Adds type-product ownership, `IfcRelDefinesByType` occurrence and sibling-map
  hierarchy evidence.
- General production logic resolves the final 16 type-owned FootPrint cases
  without hard-coded STEP IDs.

## Assessment, performance and safety

- Adds IFC+SG likelihood and exporter evidence.
- Adds file-size categories and `FULL_SEMANTIC`, `HYBRID`,
  `STREAMING_FIRST`, and `LIMITED_AUDIT` strategies.
- Adds duplicate STEP-ID pre-scan and explicit added/deleted-record reporting.
- Optimizes the 622.7 MB pre-scan from 40.17 to 9.50 seconds.
- Full large-model transaction: 82.90 seconds, 16/16 verified, zero unexpected
  records.
- Patch layer verified at 50 MB, 500 MB and 1 GB.

## UI, reports and packaging

- Adds IFC+SG file assessment and audit-result categories to the desktop UI.
- Updates PDF/HTML wording, shareable-path privacy and regulatory disclaimer.
- Adds Windows version metadata, notices and bundled rule metadata.
- Adds synthetic IFC4 fixture factory, expanded tests and production documents.

---
