# Large-file performance

The desktop Scan action performs one IfcOpenShell parse followed by direct slab target
collection, one context index, and signature-cached resolution. It deliberately skips
the redundant global pre-scan, full schema/EXPRESS validation, SHA-256 hashing, and
whole-model semantic snapshots.

Repair parses the source once, writes one same-volume temporary output, verifies exact
target offsets from the writer manifest, and atomically installs the result. Reopening
and full schema validation are optional. Save As leaves the original untouched.

On the supplied small faulty Revit 2025 multiple-linked fixture, after runtime warm-up,
three quick scans took 0.006–0.008 seconds each. Three full analyses took 1.74–1.96
seconds each; schema/EXPRESS validation accounted for almost all of the difference.
These small-file results are directional and must not be extrapolated to gigabyte files.

For a large-file benchmark:

```powershell
ifc-context-repair benchmark model.ifc --quick-scan
ifc-context-repair benchmark model.ifc --profile model.profile
```

Record file size, filesystem type, available RAM, prescan, parse, diagnosis, validation,
write, and peak Python memory. Native IfcOpenShell allocations are not completely
captured by `tracemalloc`, so Windows Task Manager or Process Explorer should also be
observed. Parsing and validation are native calls and cannot be interrupted mid-call;
cancellation is honored before and after those stages.
