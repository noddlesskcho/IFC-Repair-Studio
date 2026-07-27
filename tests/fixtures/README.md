# Synthetic IFC4 Fixture Matrix

`synthetic_ifc.py` builds small IFC4 files without production STEP-ID
assumptions. The unit and integration tests combine these semantic fixtures with
byte-level mutation to cover:

- valid IFC+SG-like model;
- direct missing Body and FootPrint contexts;
- shape-aspect missing context;
- representation-map missing context;
- type-owned FootPrint map without occurrences;
- mapped use with agreeing or conflicting evidence;
- multiple compatible contexts;
- orphaned representation;
- IfcSpace without Body;
- Base Quantity `MethodOfMeasurement` review;
- projected CRS and map conversion;
- malformed STEP, dangling reference and duplicate STEP-ID safety cases.

Large binary fixtures remain external and are enabled through the documented
`IFC_*_FIXTURES` environment variables so the repository stays small.
