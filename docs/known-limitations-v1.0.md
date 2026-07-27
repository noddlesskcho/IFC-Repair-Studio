# Known Limitations — Version 1.0

- Repair support is limited to IFC4 IFC+SG workflows.
- IFC2X3 and IFC4X3 receive no automatic repair.
- Automatic repair is enabled only for identifiable Autodesk Revit 2025 and
  Autodesk Revit 2026 IFC+SG exports.
- Other exporters receive audit results only.
- The tool is not an official CORENET X validator and does not guarantee approval.
- Space Body, quantity, and georeferencing rules are beta and report-only.
- Georeferencing checks prove entity/reference structure, not real-world survey
  correctness.
- Quantity expectations can depend on submission scope; the application does
  not infer or create quantities.
- Missing space geometry is never created.
- Only three representation signatures are repairable in version 1.0.
- Full semantic loading can require several times the IFC file size in RAM.
- Files above 2 GB have streaming infrastructure but have not received complete
  semantic end-to-end qualification in this release.
- The largest semantic end-to-end regression model is 622.7 MB. The patch layer
  is separately exercised with a 1 GB synthetic IFC.
- ZIP input must contain exactly one `.ifc`.
- Existing unrelated IFC problems remain unchanged and may still be reported by
  official validators.
