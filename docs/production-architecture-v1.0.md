# Production Architecture — IFC+SG Repair Assistant 1.0

## Positioning

The product is an IFC+SG pre-submission technical audit and targeted repair
application for CORENET X workflows. It does not claim regulatory compliance.

## Execution path

```text
PySide6 MainWindow
  -> TaskWorker in QThread
  -> archive/file preparation
  -> STEP envelope and lightweight pre-scan
  -> IFC+SG assessment and strategy selection
  -> IfcOpenShell semantic load when allowed
  -> shared relationship/context indexes
  -> IFC+SG registry selects applicable rules
  -> independent detection/classification
  -> explicit repair plan
  -> user approval
  -> source fingerprint and output preflight
  -> ordered variable-length patch plan
  -> stream source once into same-directory temporary IFC
  -> flush and fsync
  -> target, record, relationship and STEP-envelope verification
  -> unexpected-change audit
  -> atomic os.replace(temp, repaired output)
  -> PDF and HTML reports
  -> completion signal
```

Heavy parsing, indexing, writing, verification, and reporting run in the worker
thread. UI updates are signal-only.

## Module boundaries

- `ui/`: presentation and workflow state only.
- `file_io.py`: `.ifc`, `.ifczip`, and safe one-IFC ZIP handling.
- `prescan.py`: streaming/memory-mapped routing evidence.
- `ifc_sg_assessment.py`: applicability, exporter, size, memory and strategy.
- `rules/ifc_sg/`: registry, metadata, production repair and beta audit rules.
- `indirect.py`: shared semantic relationship/context indexes.
- `step_patch.py`: immutable-source targeted writer.
- `target_verification.py` and `change_audit.py`: mandatory integrity proof.
- `reporting.py`: concise PDF and interactive HTML.
- `diagnostics.py`: timing, memory, CPU, disk and rotating logs.

## Strategy selection

| Category | Size | Default strategy |
|---|---:|---|
| Small | below 100 MB | `FULL_SEMANTIC` |
| Medium | 100–500 MB | `HYBRID` |
| Large | 500 MB–2 GB | `HYBRID` or `STREAMING_FIRST` based on RAM |
| Very large | above 2 GB | `STREAMING_FIRST` or `LIMITED_AUDIT` |

These are operational categories, not validity limits. IFC2X3 and IFC4X3 use
`LIMITED_AUDIT` and cannot be repaired in version 1.0.

## Safety invariants

1. Source IFC bytes are never modified.
2. Output is written once.
3. Only approved `IfcShapeRepresentation.ContextOfItems` tokens may change.
4. `$` to variable-length `#id` edits use stream-copy, never in-place mutation.
5. Context IDs are resolved semantically and are never hard-coded.
6. Only `HIGH` confidence proposals can reach the writer.
7. Unexpected changes prevent successful publication.
8. Cancellation before atomic installation removes incomplete temporary output.
