# IFC Repair Studio v0.4 acceptance checklist

- [x] Recommended workflow never renames the original IFC.
- [x] Default repaired filename is shown before repair.
- [x] Repair becomes the primary action after issues are found.
- [x] Scan Again becomes secondary after scan.
- [x] Element and representation metrics are labelled separately.
- [x] Scan, repair, verification, and reporting run in a worker thread.
- [x] Coarse `Writing atomic output` status is replaced by named stages.
- [x] Elapsed time and temporary output size are shown during repair.
- [x] One same-volume temporary output stream is written per repair.
- [x] `os.replace()` installs verified output without a post-write copy.
- [x] Fast targeted verification is default; full validation is optional.
- [x] Failure UI includes stage, source-safety guidance, and log path.
- [x] Large native stages use honest indeterminate progress.
- [x] Automatic scope remains `SLAB_MISSING_SHAPE_CONTEXT_V1` only.
- [x] Rule and target models permit additional explicit rules later.
- [x] Multi-resolution icon is embedded and loaded at app/window level.
- [x] Non-slab ownership paths are excluded by integration tests.
- [x] Large sample passes 2,552 / 2,051 / 4,851 / 3,151 counts.
- [x] 29 tests pass with the large sample enabled.
- [x] Windows portable executable reaches the GUI event loop.

## Migration notes

- Default desktop output changes from replace-original to Save As.
- Default CLI output also uses `<stem>_repaired.ifc` without a backup.
- CLI overwrite requires `--replace-original`; optional full validation uses
  `--full-validation`.
- Backups now use `.original.ifc` and timestamped collision variants.
- `RepairConfig.full_validation` defaults to `False`.
- Reports include rule ID/version and targeted verification separately from full IFC
  validation.
- Old `semantic` writer selection is removed from the current slab-rule release; the
  byte-preserving targeted writer remains schema-gated by rule detection.
