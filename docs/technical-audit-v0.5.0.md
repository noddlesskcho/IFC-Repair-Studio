# IFC Repair Studio 0.5.0 element-policy audit

## Outcome

Version 0.5.0 preserves the one-write, byte-preserving v0.4.2 repair transaction and
adds separately constrained policies for `IfcWall`, `IfcOpeningElement`, `IfcRailing`,
and `IfcCovering`. The original `IfcSlab` policy remains unchanged.

The desktop application presents one **Repair All Safe Issues** operation. Internally,
each representation is collected, resolved, confidence-gated, patched, and verified
independently. All accepted edits are installed through one temporary output and one
atomic replacement.

## Enabled policy boundaries

| Product policy | Qualified representation signatures |
|---|---|
| IfcSlab | Body / SweptSolid; FootPrint / Curve2D |
| IfcWall | Axis / Curve3D; Body / SweptSolid; Body / Tessellation |
| IfcOpeningElement | Body / SweptSolid; Body / Tessellation |
| IfcRailing | Body / MappedRepresentation; Body / SweptSolid; Body / Tessellation |
| IfcCovering | Body / SweptSolid; Body / Tessellation; FootPrint / Curve2D |

Only direct `IfcProduct.Representation ->
IfcProductDefinitionShape.Representations` ownership is eligible. Representation maps,
shape aspects, unsupported signatures, low-confidence decisions, and ambiguous
decisions are never automatically changed. `IfcOpeningElement` additionally requires
an `IfcRelVoidsElement` host relationship.

## Context evidence

The resolver retains deterministic sibling, same-product, clean-profile,
identifier/view, and project-connectivity evidence. Version 0.5.0 adds exact same-file
semantic peer evidence keyed by:

```text
RepresentationIdentifier
RepresentationType
first representation item class
```

Product class is deliberately excluded from that evidence because
`IfcGeometricRepresentationContext` describes the geometry view rather than the
product. The candidate must still exist in the current IFC, be connected to its
`IfcProject`, match the identifier, have a compatible target view, win by the configured
score margin, and have no conflicting semantic contexts.

## Retained 652.9 MB sample

The retained input had already received the v0.4.2 slab-only repair. Its remaining
policy results were:

| Product | Elements scanned | Representations scanned | Affected | Safe |
|---|---:|---:|---:|---:|
| IfcSlab | 2,552 | 4,851 | 0 | 0 |
| IfcWall | 15,055 | 29,749 | 0 | 0 |
| IfcOpeningElement | 9,312 | 9,312 | 5,738 | 5,738 |
| IfcRailing | 613 | 613 | 0 | 0 |
| IfcCovering | 37 | 74 | 37 | 37 |
| **Total** | **27,569** | **44,599** | **5,775** | **5,775** |

All 5,738 affected openings participated in `IfcRelVoidsElement`; zero were orphaned.
Openings resolved to the project-connected Body context `#26`. Covering FootPrint
representations resolved to the project-connected FootPrint context `#28`.

The end-to-end repair produced:

```text
Intended target records: 5,775
Verified target records: 5,775
Actual modified STEP records: 5,775
Unexpected modified STEP records: 0
Targeted issues after output rescan: 0
```

The original input was never opened for writing. The repaired output was created at a
different path through the existing same-directory temporary-file transaction.

## Timing

Measured on the local Windows 11 workstation:

| Stage | Seconds |
|---|---:|
| IfcOpenShell parse | 45.917 |
| Collect supported products | 0.056 |
| Collect direct shape representations | 0.466 |
| Build context index | 1.238 |
| Resolve contexts | 0.768 |
| Build patch plan | 5.618 |
| Stream and apply 5,775 patches | 0.826 |
| Flush/fsync | 0.336 |
| Exact target verification | 0.033 |
| Unexpected-change audit | 1.330 |
| PDF report | 0.033 |
| HTML report | 0.181 |
| **Total repair** | **57.626** |

Native IfcOpenShell parsing remains the dominant bottleneck. The 652.9 MB output is
still written only once. Progress callbacks during patch planning and streaming are
throttled to bounded intervals so large target counts do not flood the Qt event queue.

## Automated verification

The local suite result is:

```text
45 passed, 3 skipped
```

The three skipped tests require private clean, faulty, and original large-file fixture
environment variables. Unit and integration coverage includes element policy scope,
orphan-opening rejection, cross-product semantic evidence, conflicting-evidence
rejection, combined slab/wall repair, source preservation, variable-length STEP
patching, exact verification, unexpected-change detection, reporting, and UI state.

The PyInstaller 0.5.0 folder build also passed an offscreen windowed launch smoke test.

## PyInstaller warning classification

- **Expected platform-specific:** `pwd`, `grp`, `posix`, `fcntl`, `termios`,
  `_posixsubprocess`, `_scproxy`, and related Unix/macOS modules.
- **Optional dependency:** `psutil`, ReportLab render backends, Lark enhancements,
  `rich`, `regex`, `olefile`, `defusedxml`, and optional font/shaping libraries.
- **False positive/dynamic API:** Numpy scalar/ufunc pseudo-module names,
  multiprocessing exported attributes, and PyInstaller bootstrap imports.
- **Development-only:** pytest/unittest helpers and test modules; intentionally
  excluded.
- **Required runtime dependency:** none missing. PySide6, IfcOpenShell, ReportLab,
  Pillow, icon resources, and Qt plugins are bundled.

`psutil` remains optional. This build uses the existing native Windows diagnostic
fallback because the build environment does not contain `psutil`; its absence is not a
repair or launch failure.

## Known limitations

- The retained large sample contains affected openings and coverings but no affected
  walls or railings. Those two policies are covered synthetically and should receive
  additional faulty real-world fixtures before universal rollout.
- The original large sample was not available in the clean workspace. Therefore the
  combined slab-plus-new-policy count was not rerun in one transaction; the unchanged
  per-slab golden assertions remain in the private-fixture test.
- IfcOpenShell parsing remains non-streaming and cannot be cooperatively cancelled
  inside the native call.
- Full IFC schema validation remains optional and was not part of the fast large-file
  benchmark.
