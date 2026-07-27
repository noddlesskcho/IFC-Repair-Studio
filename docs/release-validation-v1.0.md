# Release validation — IFC+SG Repair Assistant 1.0.0

## Release status

The v1.0.0 build is a specialised IFC+SG pre-submission audit and repair tool
for CORENET X projects. It is not an official validator and does not guarantee
regulatory acceptance.

## Automated tests

- 65 passed
- 3 skipped because external golden-fixture environment variables were not configured
- no failed tests

The large sample was instead exercised directly through the production rule
engine and benchmark path.

## Packaged executable test

Executable:
`dist/IFCSGRepairAssistant-1.0.0/IFCSGRepairAssistant-1.0.0.exe`

The frozen executable processed a synthetic IFC4 IFC+SG fixture through the
production repair pipeline and produced a repaired IFC, PDF summary, HTML
Detailed Report, diagnostic log, and JSON self-test evidence.

- intended repairs: 2
- successfully repaired: 2
- targeted issues remaining: 0
- report-only findings: 3
- target verification: passed
- unexpected modified records: 0
- runtime errors: 0

The original fixture was not overwritten.

Final executable SHA-256:
`27E664BD0912CDA56E463695197975C4B94C7D72933C97E294F5F0E59D683668`

## Large IFC regression

Input size: 652,954,035 bytes (622.7 MB)

| Stage | v1 initial | v1 optimised |
|---|---:|---:|
| Streaming pre-scan | 40.17 s | 9.50 s |
| Total production run | 108.58 s | 82.90 s |

Production outcome:

- representations scanned: 142,504
- final type-owned FootPrint targets: 16
- high-confidence repaired: 16
- targeted issues remaining: 0
- unexpected modified records: 0
- output growth: 32 bytes
- peak working set: 4,812,673,024 bytes

The primary bottleneck is IfcOpenShell semantic loading (47.12 s), followed by
relationship-index construction (7.30 s). The streaming patch itself took
0.41 s.

## Patch throughput

| Synthetic size | Total patch test |
|---:|---:|
| 50 MB | 0.465 s |
| 500 MB | 4.673 s |
| 1 GB | 9.726 s |

All sizes passed targeted verification and unexpected-change audit.

## Safety assertions

- The source IFC is never the writer destination.
- Variable-length `$` to `#STEPID` changes use ordered stream-copy patches.
- Temporary output is created beside the final output.
- Publication uses `os.replace` only after verification.
- Cancellation before publication removes incomplete temporary output.
- Any unexpected STEP-record modification fails publication.
- Report generation occurs after repaired-IFC verification.

## Known validation boundary

The largest end-to-end semantic test is 622.7 MB. The 1 GB result tests the
streaming patch and verification path, not full IfcOpenShell semantic loading.
Very-large-file operation therefore remains strategy- and hardware-dependent.
