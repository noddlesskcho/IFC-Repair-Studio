# Sample diagnosis

## Clean reference samples received

Eight clean IFC4 samples were supplied on 17 July 2026 and inspected read-only:

- Revit 2024: native single/multiple and linked single/multiple slabs;
- Revit 2025: native single/multiple slabs;
- Revit 2026: native single/multiple slabs.

All eight produced zero missing-context prescan candidates and zero IfcOpenShell
validation issues (including EXPRESS rules). They are positive baselines, not faulty
fixtures. No supplied faulty sample is currently in scope, so there is still no
clean-versus-faulty repair result to claim.

Across the listed samples, every ordinary slab Body representation uses the `Body`
geometric subcontext under the project Model context with `MODEL_VIEW`. Every present
FootPrint representation uses the `FootPrint` subcontext under that same Model context,
also with `MODEL_VIEW`. STEP IDs vary by exporter generation and are not part of the
rule: Body is #24 in the listed Revit 2024 files, #26 in Revit 2025, and #15 in Revit
2026; FootPrint is respectively #26, #28, and #17.

The Revit 2026 multiple-native sample contains one product-owned Body representation
and a semantically identical Body representation owned by an `IfcShapeAspect`. Both
validly use the Body subcontext. The product index now traces this shape-aspect path
back through `PartOfProductDefinitionShape` instead of treating it as an orphan.

## IFC relationship under investigation

In IFC4, the first inherited `IfcRepresentation` attribute on an
`IfcShapeRepresentation` is `ContextOfItems`. It refers to an
`IfcRepresentationContext`; in normal geometric product representations this is an
`IfcGeometricRepresentationContext` or subcontext. A STEP `$` represents an unset
attribute. At this required location it is malformed, even though `$` is valid for
many optional attributes elsewhere.

Typical traversal is:

`IfcSlab.Representation` → `IfcProductDefinitionShape.Representations` →
`IfcShapeRepresentation.ContextOfItems` → geometric subcontext → parent context →
`IfcProject.RepresentationContexts`.

Mapped/type geometry can instead be reached through `IfcRepresentationMap`; the index
records that owner and does not pretend it is a slab occurrence when no occurrence can
be established.

## Proposed rule confirmed against the supplied faulty samples

1. Reject contexts not rooted in the same `IfcProject` representation context graph.
2. Prefer a valid same-identifier sibling.
3. Prefer the statistically consistent context used by same-file representations with
   matching product class, identifier, type, and first geometry item class.
4. Add weaker identifier and target-view compatibility evidence.
5. Require a clear score margin. A tie or near tie is ambiguous.
6. Automatically change only `Safe to repair`; warning cases require opt-in.

Identifier-only evidence produces a warning, not a safe repair. No suitable rooted
context is not repairable. Two equally supported Body subcontexts are ambiguous.

## Exact entities that would change

None of the eight listed clean files would change. Four linked-model faulty files were
then supplied and contain 11 affected representations:

- Revit 2025 multiple linked: Body #97, #106, #115, #124 → local Body context #26;
  FootPrint #134, #137, #140, #143 → local FootPrint context #28.
- Revit 2025 single linked: FootPrint #104 → local FootPrint context #28.
- Revit 2026 multiple linked: shape-aspect Body #110 → local Body context #15.
- Revit 2026 single linked: FootPrint #88 → local FootPrint context #17.

These STEP IDs describe these files only. Selection was based on project-rooted context
properties, matching representation/product/item signatures, same-file evidence where
available, and 34 equivalent representations across the supplied clean baselines.

Targeted-patch proof-of-concept results: 11 changes, 22 validation issues resolved,
zero issues after repair, zero new issues, all outputs reopened, all affected-product
geometry tests passed, and an independent reverse-patch comparison confirmed that every
non-target byte was preserved. CORENET X and IFC+SG external testing remain outstanding.
