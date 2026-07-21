# Known limitations and risks

- No clean/faulty customer IFC fixtures were available, so Revit 2025 IFC+SG patterns
  and linked-slab equivalence have not been empirically confirmed.
- IfcOpenShell must parse the semantic model in memory; files above 1 GB need real
  profiling on the target workstation.
- Native parse and write calls are not safely cancellable mid-call.
- Multiple `IfcProject` populations require additional project-membership tracing; the
  current conservative root set may downgrade or reject complex cases.
- `IfcRepresentationMap` is indexed, but occurrence resolution through every mapped
  type relationship is intentionally conservative.
- The geometry option is implemented as a focused helper; product-level results still
  need wiring into the top-level report before it should be exposed in a release build.
- Atomic rename is reliable only within one filesystem. Network shares have server-
  specific durability semantics.
- PyInstaller output and Windows code signing must be tested on a clean Windows VM.
- CORENET X viewer/checker and the IFC+SG validator were not available for testing.

Threats include maliciously large records, parser defects in native code, disk
exhaustion, read-only/network paths, and misleading but valid-looking context patterns.
Mitigations are bounded streaming, size policy, free-space checks, temporary outputs,
reopen/validation, conservative confidence gates, and a complete audit record.
