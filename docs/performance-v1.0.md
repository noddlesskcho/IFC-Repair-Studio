# Performance Results — Version 1.0

Measured on the development Windows workstation. Results are evidence for this
environment, not promised minimum speeds.

## Large semantic end-to-end regression

Input: 652,954,035 bytes (622.7 MB), IFC4, 3,536,612 STEP lines.

| Metric | Initial v1 implementation | Optimized v1 |
|---|---:|---:|
| Total repair transaction | 108.58 s | 82.90 s |
| Lightweight pre-scan | 40.17 s | 9.50 s |
| IfcOpenShell semantic load | 41.97 s | 47.12 s |
| Shared indirect index | 6.25 s | 7.30 s |
| Patch-plan scan | 4.44 s | 4.49 s |
| Stream output | 0.43 s | 0.41 s |
| Unexpected-change audit | 1.25 s | 1.10 s |
| Peak working set | 4.48 GiB | 4.48 GiB |
| Final repairs | 16/16 | 16/16 |
| Unexpected records | 0 | 0 |

The broad regex pre-scan was replaced with a narrow shape keyword scan, one
streaming entity pass and a compact STEP-ID bitset. This reduced pre-scan time
by 76% and total time by 24%.

The actual IFC writer is not the bottleneck. Native IfcOpenShell parsing is the
largest stage, followed by pre-scan/index construction. Peak memory is caused by
the semantic model and native allocations, not the variable-length patch writer.

The run selected `HYBRID`, scanned 78,789 products and 142,504 shape
representations, repaired the final 16 type-owned FootPrint maps, and verified
zero remaining targeted issues.

## Streaming patch-layer size tests

| Synthetic IFC | Total | Plan | Output write | Verification | Change audit | Result |
|---:|---:|---:|---:|---:|---:|---|
| 50 MB | 0.47 s | 0.29 s | 0.03 s | 0.03 s | 0.09 s | Pass |
| 500 MB | 4.67 s | 3.03 s | 0.40 s | 0.03 s | 0.93 s | Pass |
| 1 GB | 9.73 s | 6.66 s | 0.65 s | 0.02 s | 1.85 s | Pass |

All tests performed a variable-length `$` to `#26` edit, verified the exact
target record, and proved no other bytes changed. Temporary files were deleted
after each benchmark.

## Operational guidance

- Provide free disk exceeding approximately 1.2 times the source plus margin.
- For large semantic audits, allow several times the IFC size in available RAM.
- Very large files with insufficient RAM select `LIMITED_AUDIT`.
- Report generation is separately timed and begins only after output integrity
  has been proved.

Machine-readable results:

- `validation-output/production-v1-large-benchmark.json`
- `validation-output/production-v1-patch-benchmarks.json`
