# Version 1 Benchmark Results

The benchmark uses one excluded warm-up and three measured iterations per completed
configuration. The sample was read from a OneDrive-synchronised SSD path, so the
results separate storage-heavy pre-scan/semantic loading from rule indexing.

## Current 623 MB sample

| Configuration | Runs | Median total | Min - max | Median pre-scan | Median semantic load | Median direct index | Median detection |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Optimised Version 1 | 3 | 62.720 s | 62.299 - 62.784 s | 9.565 s | 39.733 s | 3.069 s | 2.176 s |
| Broad indirect baseline | Warm-up only | >420 s | Timed out | - | - | - | - |

The broad warm-up reproduced the long scanning state and was terminated after
seven minutes. A precise percentage improvement is deliberately not claimed. The
measured lower bound is greater than 85% for total scan duration, while the exact
broad duration is unknown.

The dominant optimized cost is IfcOpenShell semantic loading, not direct-product
indexing. Output streaming remains proportional to file size and is not expected to
improve when the number of enabled ownership categories changes.

The final end-to-end repair took about 136 seconds wall-clock including a second
semantic reopen. Targeted patch writing itself took under one second; semantic IFC
loading and reopen verification dominated.

Small-file broad, detection-only and Version 1 configurations each completed three
measured runs. See `validation-output/version1-benchmark/benchmark_results.json`,
`benchmark_results.csv`, `benchmark_summary.html`, and `benchmark_limitations.json`.

No 100-500 MB or >1 GB valid IFC was available. No synthetic duplicated STEP file
is presented as a representative semantic benchmark. During a cold sample warm-up,
Windows process inspection showed approximately 2.9 GB working set; psutil was not
available in the source-test runtime, so that observation is not reported as a
precise peak-RSS measurement.
