# IFC Repair Studio 0.4.2 technical audit

## Proven production execution path

```text
MainWindow.repair (GUI thread)
  -> MainWindow._start_job
  -> TaskWorker.run (dedicated QThread)
  -> repair_file
     -> _analyse_loaded -> ifcopenshell.open -> slab rule detection/resolution
     -> preflight_output / abandoned-temp cleanup
     -> build_patch_plan -> validate_patch_plan
     -> create hidden same-directory temporary output
     -> apply_patch_plan (mmap read + one sequential output stream)
     -> flush + fsync
     -> size and STEP-envelope verification
     -> exact target-record verification
     -> unintended-change audit
     -> optional IfcOpenShell full validation
     -> os.replace(temp, final)
     -> PDF report -> HTML report
     -> TaskWorker.completed -> MainWindow._completed (GUI thread)
     -> QThread.quit / deleteLater
```

The Repair button is connected in `ui/main_window.py:364`. `repair()` creates an
immutable `RepairConfig` and `_start_job()` moves `TaskWorker` to a new `QThread`.
All IFC, file, verification, and reporting work therefore runs in that worker. Only
queued Qt signals update widgets. The running-thread guard and disabled button prevent
duplicate repair jobs. Closing requests cooperative cancellation and leaves the window
open until the worker exits.

| Stage | Code | Whole IFC in Python memory | Disk I/O / copy | Reparse | Blocking/failure/cancellation |
|---|---|---:|---|---:|---|
| UI command/thread | `ui/main_window.py:607,653`; `TaskWorker.run:90` | No | No | No | Non-blocking GUI; exception context is signalled |
| Metadata/preflight | `repair.py:200`; `output_safety.py:31` | No | metadata, free-space and fsynced write probe | No | Can fail before output; safely cancellable between checks |
| IFC open | `repair.py:73`; `parser.open_model` | Native IfcOpenShell model | sequential source read by IfcOpenShell | Yes, source once | Long native call; cannot safely cancel mid-call |
| Slabs/reps/context | `rules.py:71`; resolver/index modules | Model already resident | No | No | Cooperative cancellation in collections/resolution |
| Patch plan | `step_patch.py:132` | No; read-only mmap | source scan only | No | Cooperative; detects duplicates/stale/missing targets |
| Plan validation | `step_patch.py:190` | No | No | No | Rejects invalid/overlapping offsets |
| Output creation | `repair.py:365`; `step_patch.py:213` | No; 8 MiB views | one stream-copy with variable-length edits | No | Cooperative; partial temp is removed |
| Durable flush | `step_patch.py:282` | No | `flush` + `fsync` | No | Not interrupted during durable flush |
| Envelope/targets | `target_verification.py:46,66` | No; read-only mmap | bounded envelope read and target records | No | Cooperative target loop; corruption fails before install |
| Change audit | `change_audit.py:34` | 8 MiB comparisons | read source and temp | No | Cooperative; any unrelated byte fails repair |
| Full validation | `repair.py` optional block | Second native model | reads temp | Optional only | Native call is not mid-call cancellable |
| Install | `repair.py:527` | No | same-volume `os.replace` | No | Atomic; deliberately non-cancellable |
| Reports | `reporting.py:442,446` | repair records | writes PDF then HTML | No | Worker thread; HTML record construction is cancellable |
| Cleanup/completion | `repair.py` finally; worker Qt signals | No | removes incomplete temp | No | Always attempted |

## Final writer finding

The production repair path does **not** call `ifcopenshell.file.write()` or
`model.write()`. It writes the repaired IFC exactly once through
`step_patch.apply_patch_plan()`. The source is mapped read-only; ordered unchanged
ranges are copied to a hidden temporary file and `$` is replaced by a variable-length
reference such as `#26` or `#123456`. The destination is flushed and fsynced, verified,
then installed with `os.replace()`.

Write/search classification:

- `model.write()` occurs only in three test fixture builders.
- `shutil.copy2()` occurs only in explicit advanced overwrite/backup mode.
- `mmap` in `step_patch.py` is the production patch planner/writer read path.
- `mmap` in `target_verification.py` and `change_audit.py` is production verification.
- `mmap` in `prescan.py` is scan-only support.
- `os.replace()` in `repair.py` is the production atomic install.
- `flush()` / `fsync()` in `step_patch.py` are the production durable temporary write;
  their use in `output_safety.py` is only the preflight probe.
- There are no production `Path.read_bytes()` or `Path.write_bytes()` calls and no
  normal-path `os.rename()`.

## Safety and format findings

The patcher accepts CRLF/LF, multiline entities, whitespace variations and keyword
case. STEP string/comment-aware record termination avoids semicolons inside strings or
comments. It rejects invalid IDs, duplicate targets, duplicate STEP records, overlaps,
non-`$` targets and changed source fingerprints. The fingerprint combines size,
nanosecond mtime and SHA-256 of both source edges. Offsets are 64-bit Python integers;
Windows 64-bit mmap supports files above 2 GB subject to OS/address-space limits.

The source is never opened for writing. Variable-length replacements are not attempted
in-place. The temp file is on the destination volume, file handles and mmap objects are
closed before install, and incomplete temp files are removed on exception/cancellation.
Antivirus or destination locks surface as normal I/O failures before the source changes.
Startup cleanup only removes app-pattern hidden temp files older than the configured
threshold.

Verification proves the STEP envelope, exact expected size, every target assignment,
unchanged representation identifier/type/items, and byte-for-byte identity outside the
planned ContextOfItems tokens. Atomic install happens only after all checks pass.

## Performance evidence

Benchmark: supplied 652,895,459-byte IFC, warm local cache, Windows x64. Report creation
and optional full validation were disabled so the repair core is comparable.

| Measurement | v0.4 baseline | v0.4.2 optimized |
|---|---:|---:|
| Total repair | 49.443 s | 32.843 s |
| IfcOpenShell open/parse | 23.581 s | 24.661 s |
| Old output serialization | 11.032 s | not used |
| Old full-output regex verification | 10.457 s | not used |
| Patch-plan scan | not separately recorded | 2.465 s |
| Stream write | included above | 0.284 s |
| Durable flush | included above | 0.211 s |
| Target verification | full scan above | 0.012 s |
| Unintended-change audit | absent | 0.670 s |
| Peak working set | not captured by baseline | 4,730,904,576 bytes |
| Output changed records | not audited | 3,151 expected / 3,151 actual / 0 unexpected |

A same-session replay of the preserved v0.4 source measured 44.420 seconds versus
32.843 seconds for v0.4.2 (26.1% faster). Process peak working set was 4,068,589,568
bytes before and 4,730,904,576 bytes after; peak private bytes were effectively flat
(4,958,928,896 versus 4,961,017,856). The higher mapped working set is the cost of the
new read-only output audit and Windows file-cache residency, not Python whole-file
allocation. The persistent private-memory bottleneck remains the IfcOpenShell model.
The optimization target was elapsed I/O and verification safety, not a claim of reduced
native model memory.

The actual bottleneck is IfcOpenShell parsing: roughly 75% of optimized elapsed time and
nearly all peak memory. Patch discovery is the second cost. Replacing the whole-file
anchored regex with a keyword-prefiltered, locally validated scan reduced patch planning
from 11.042 seconds to 2.465 seconds. The output stream itself is not the bottleneck.

The 653 MB supplied sample serves as the 500 MB-class production benchmark. A 1 GB
physical-write benchmark was not run on this workstation because only about 1.1 GB was
free; consuming nearly all free space would violate the application's own 1.2x safety
margin. `scripts/benchmark_repair.py` is repeatable on a suitably provisioned machine
and records throughput, peak RAM, stage timings, counts and verification results.

| Patch I/O benchmark | Result | Plan | Write + flush | Verify + audit | Throughput |
|---|---:|---:|---:|---:|---:|
| 50 MiB synthetic | 0.327 s total | 0.210 s | 0.042 s | 0.071 s | 2.22 GB/s (warm cache) |
| 500 MiB synthetic | 3.069 s total | 1.827 s | 0.422 s | 0.784 s | 2.31 GB/s (warm cache) |
| 653 MB real IFC (500 MB class) | 32.843 s total | 2.465 s | 0.495 s | 0.712 s | 2.30 GB/s (warm cache) |
| 1 GiB synthetic | 7.071 s total | 4.419 s | 0.959 s | 1.605 s | 2.29 GB/s (warm cache) |

Peak working set was 160,485,376 bytes (50 MiB), 1,100,017,664 bytes (500 MiB), and
2,207,322,112 bytes (1 GiB). This largely reflects Windows mapping/cache accounting;
the Python writer operates on 8 MiB views and does not read the complete file into a
Python `bytes` object. The semantic 653 MB repair peaked at 4,730,904,576 bytes because
the IfcOpenShell object model is resident.

These are local warm-cache results, not speed assertions. The benchmark scripts emit
JSON baselines so later builds can be compared by relative regression.

## Packaging warning classification

The 0.4.2 spec no longer uses broad `collect_all(reportlab)` / `collect_all(PIL)`, which
previously pulled development and NumPy test surfaces into analysis. It keeps the build
windowed, bundles the icon, relies on standard Qt/ReportLab hooks, explicitly includes
IfcOpenShell native data, and excludes OCC because 3D rendering is not part of the GUI
repair path.

- `pwd`, `grp`, `posix`, `fcntl`, `termios`, `_posixsubprocess`: expected non-Windows.
- `pytest`, `_pytest`, setuptools test helpers, NumPy testing helpers: development-only
  and excluded.
- `OCC`: optional 3D geometry dependency, intentionally excluded.
- `psutil`: optional diagnostics. The spec includes it when installed; native Windows
  memory telemetry remains available otherwise. Missing psutil is never fatal.
- ReportLab and PySide6 imports/resources used by the application: required runtime;
  confirmed through PDF generation and packaged-executable smoke tests.

## Known limitations

- Native IfcOpenShell parse and optional full validation cannot expose safe granular
  cancellation or record-level progress.
- A separate Scan then Repair deliberately reparses the source so a stale resident model
  is never repaired and a multi-gigabyte model is not retained indefinitely.
- Edge fingerprinting is designed to detect normal source replacement/edit races; it is
  not a cryptographic hash of the entire file.
- `fsync` asks Windows to durably flush, but physical storage/driver guarantees remain
  outside application control.
- Full schema validation is optional; fast verification is deliberately scoped to this
  slab rule and does not claim general IFC conformance.
