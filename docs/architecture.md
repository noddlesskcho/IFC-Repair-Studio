# Architecture Decision Record: Windows IFC context repair utility

**Status:** Accepted, 17 July 2026

## v0.5 module boundaries

- `rules.py`: versioned repair-rule contract, `RepairTarget`, and element policies;
- `repair.py`: stage-instrumented orchestration and file-safety transaction;
- `context_index.py`, `detector.py`, `resolver.py`: schema-aware collection and proposal;
- `step_patch.py`: byte-preserving, manifest-producing targeted persistence;
- `target_verification.py`: fast output-envelope and assignment verification;
- `naming.py`: deterministic Save As and overwrite-backup naming;
- `telemetry.py`: structured stage updates consumed by CLI or UI workers;
- `reporting.py`: modular executive PDF and offline engineering HTML builders, with
  explicit on-demand JSON/CSV export services;
- `diagnostics.py`: opt-in developer logging, isolated from user-facing reports;
- `ui/main_window.py`: workflow state rendering;
- `app.py`, `resources.py`: Windows identity and packaged-resource integration.

`PRODUCT_MISSING_SHAPE_CONTEXT_V2` combines separately qualified policies for
`IfcSlab`, `IfcWall`, `IfcOpeningElement`, `IfcRailing`, and `IfcCovering`. Adding an
entity class still requires explicit ownership, signature, candidate-context,
confidence, and verification constraints; a missing `$` alone is never sufficient.
Openings additionally require an `IfcRelVoidsElement` host relationship.

## Decision

Use Python 3.11/3.12, IfcOpenShell 0.8.x, PySide6, and PyInstaller. The core is a
UI-independent package. A streaming byte-state-machine prescan finds candidates;
IfcOpenShell performs authoritative semantic inspection and context resolution. The
production writer then creates one ordered variable-length STEP patch plan, streams
the source into a same-directory temporary file, verifies exact target records and
unexpected changes, and atomically installs the verified output. Full IfcOpenShell
schema validation remains optional.

IfcOpenShell 0.8.5 documentation confirms Windows wheels for Python 3.11–3.14,
model open/write and entity attribute assignment, JSON validation, and optional
EXPRESS rules. The dependency range is deliberately pinned to the reviewed 0.8 API
family and should be retested before adopting 0.9.

## Why

- Python and IfcOpenShell provide the most direct, schema-aware implementation.
- PySide6 has mature Windows accessibility, threading, file dialogs, tables, and
  deployability without adding a second language runtime boundary.
- PyInstaller creates a self-contained Windows folder/executable; one-folder builds
  are recommended first because native IfcOpenShell and Qt plugins are easier to audit.
- A text prescan keeps the UI responsive for large inputs. Semantic parsing is not
  streaming: IfcOpenShell may load the full model, and the app states that limitation.

## Alternatives assessed

| Alternative | Assessment |
|---|---|
| .NET/C# UI plus Python subprocess | Good enterprise UI, but doubles packaging, IPC, error handling, and versioning. No benefit for this focused utility. |
| C# UI plus IfcOpenShell CLI | Process isolation can help crash containment, but structured entity/audit data becomes an IPC contract. Consider later if native parser isolation proves necessary. |
| Direct STEP text processing | Preserves formatting but cannot defensibly resolve project/product/context semantics alone. Unsafe as the primary mode. |
| Hybrid prescan + semantic repair | Selected. Balances fast discovery with schema-aware decisions. |
| xBIM | Not selected. It adds a different semantic stack and no identified advantage for this narrowly scoped repair. |

## Components

`prescan` → `parser` → `context_index` → `detector` → `resolver` → `repair` →
`validator` → `comparator`/`reporting`. The CLI and UI depend on this pipeline but
the pipeline never imports PySide6.

The UI Scan path is intentionally lighter than Repair: it omits whole-model snapshots,
hashing, and schema/EXPRESS validation. Repair always repeats authoritative diagnosis
against the current file and performs the full safety checks before atomic replacement.

## Operational consequences

The parser stage can consume memory proportional to model size. Cancellation occurs
between expensive library calls because an in-progress native parse/write cannot be
safely interrupted. External validators are adapter work still to be integrated when
their callable interfaces and licences are available.
