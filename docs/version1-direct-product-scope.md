# Version 1 Direct-Product Repair Scope

IFC+SG Repair Assistant Version 1 repairs supported missing geometry references
on directly owned product representations exported from Revit.

## Enabled production rule

`DIRECT_PRODUCT_MISSING_CONTEXT_V1` follows only:

`IfcProduct -> IfcProductDefinitionShape -> IfcShapeRepresentation`

Supported signatures are Body / SweptSolid, Body / Tessellation and FootPrint /
Curve2D. The owning product class is recorded but is not an eligibility allow-list.
A repair requires direct ownership, a missing context, one unique compatible
project-connected semantic context, and no conflicting evidence.

## Retained disabled rules

ShapeAspect and RepresentationMap implementations remain isolated in the rule
registry with their automated relationship tests. Version 1 feature flags disable
them before detection, ownership-index construction, classification and reporting.
Developer mode is required to enable them for internal testing.

The normal diagnostics page reports `Skipped because rule disabled`; it never
reports zero issues for a category that was not scanned.

## Safety and verification

The source IFC is never modified. The writer stream-copies the source into a
same-directory temporary output and changes only the first ContextOfItems field of
approved IfcShapeRepresentation records. Publication requires targeted record
verification, semantic reopen/entity-count verification, and an exact changed-record
audit with zero unexpected records.

## Sample regression

- Direct-product targets: 8,926
- IfcSlab: 3,151
- IfcOpeningElement: 5,738
- IfcCovering: 37
- Verified repairs: 8,926
- Supported issues remaining: 0
- Unexpected changed records: 0

Missing geometry references under IfcShapeAspect and IfcRepresentationMap are
outside the Version 1 repair scope and were not modified.
