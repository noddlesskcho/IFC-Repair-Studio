# v0.6 Technical Audit and Production Debt

## Production-ready components retained

- `step_patch.py`: read-only memory mapping, ordered variable-length edits,
  source fingerprint validation, streaming output, `flush` and `fsync`.
- `target_verification.py`: STEP envelope checks, exact target-token checks, and
  exact target-record comparison.
- `change_audit.py`: byte-for-byte proof that ranges outside approved
  `ContextOfItems` tokens are unchanged.
- `repair.py`: same-directory temporary output, output preflight, atomic
  installation, cancellation boundaries, stage timings, and cleanup.
- `ui/main_window.py`: `QThread` worker ownership, queued signals, no worker
  widget access, duplicate-job prevention, and safe close handling.
- `diagnostics.py`: optional psutil telemetry with a Windows API fallback and
  rotating debug logs.

## Debt found

1. One combined classifier was presented as one active rule even though it
   contained four logically independent rules.
2. Supported schemas incorrectly included IFC2X3 and IFC4X3.
3. There was no IFC+SG applicability assessment or exporter evidence.
4. There was no `.ifczip` or one-IFC `.zip` input path.
5. File size did not select or report a processing strategy.
6. Representation-map resolution inspected `IfcMappedItem` usage but did not
   index `IfcTypeProduct.RepresentationMaps` or `IfcRelDefinesByType`.
7. Space Body, quantity, and georeferencing checks were absent.
8. Reports exposed full local paths and lacked the regulatory disclaimer.
9. The UI used “Extended Repair”, did not show IFC+SG assessment, and retained
   a source-replacement option.
10. The first broad entity-count pre-scan used a costly whole-file regex.

## Production changes

- Added a registry with seven versioned IFC+SG rules and explicit maturity.
- Restricted repair to IFC4.
- Added lightweight STEP routing, schema/exporter/IFC+SG assessment, duplicate
  STEP-ID detection, and size-aware strategy selection.
- Added safe archive extraction with exactly-one-IFC enforcement.
- Added type-product and type-occurrence indexes and the evidence-based final
  FootPrint map rule.
- Added three report-only beta audits.
- Removed source replacement from the production UI and CLI.
- Added shareable path handling, rule diagnostics, and disclaimer.
- Replaced the slow pre-scan regex with keyword scanning plus a streaming record
  pass.

## Remaining risks

- IfcOpenShell semantic loading remains the peak-memory stage.
- Very large files can require `LIMITED_AUDIT` when available RAM is insufficient.
- Beta audit rules report technical evidence but do not encode every official
  submission-scope requirement.
- External official CORENET X validation remains outside this application.
