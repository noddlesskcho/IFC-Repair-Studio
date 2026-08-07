# Release validation — IFC+SG Repair Assistant 1.0.0

## Release status

Version 1 repairs only supported missing geometry references on direct product
representations. ShapeAspect and RepresentationMap implementations are retained
for development but are disabled before detection and indexing.

## Automated tests

- 79 passed
- 3 skipped because external golden-fixture environment variables were not configured
- no failed tests

## Packaged executable test

Executable:
`release/IFCSGRepairAssistant-1.0.0/IFCSGRepairAssistant-1.0.0.exe`

The frozen executable processed the small IFC4 fixture through IfcOpenShell,
targeted STEP patching, verification, PDF generation and HTML generation.

- intended repairs: 8
- successfully repaired: 8
- supported issues remaining: 0
- target verification: passed
- unexpected modified records: 0
- runtime errors: 0

File version and product version: `1.0.0`

Final executable SHA-256:
`DF2BC353B1AA72F6F507BDC84270FE4E0785EA3894B649E57E724A5AF7A2F039`

## 622.6 MB sample regression

- direct-product representations repaired: 8,926
- IfcSlab: 3,151
- IfcOpeningElement: 5,738
- IfcCovering: 37
- supported issues remaining: 0
- expected and actual changed records: 8,926
- unexpected changed records: 0
- added or deleted STEP records: 0
- semantic entity-count differences: none
- total measured repair duration: 130.567 seconds
- targeted patch application: 0.422 seconds
- semantic reopen verification: 47.830 seconds
- peak working set reported by Windows diagnostics: 3.8 GB

The source IFC remained the read-only input. The repaired IFC was written to a
new output path and installed only after verification.

## Repeatable benchmark

The optimised Category-A-only scan completed three measured 622.6 MB runs with
a 62.720-second median (62.299–62.784 seconds). The broad indirect warm-up
exceeded 420 seconds and was stopped, so no fabricated precise percentage is
claimed. Small-file broad, repair-stage-only and optimised configurations each
have three measured runs in the benchmark artifacts.

No valid 100–500 MB or greater-than-1 GB semantic IFC fixture was available.
That limitation is recorded in the benchmark output.

## Safety assertions

- The source IFC is never the writer destination.
- Variable-length `$` to `#STEPID` edits use ordered stream-copy patches.
- Temporary output is created beside the final output.
- Publication uses `os.replace` only after verification.
- Cancellation before publication removes incomplete temporary output.
- Any unexpected STEP-record modification fails publication.
- Reports are generated only after repaired-IFC verification.

This application is not an official CORENET X validator and does not guarantee
regulatory acceptance.
