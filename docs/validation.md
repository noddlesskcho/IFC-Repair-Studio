# Validation and change control

Input checks cover path, extension, IFC STEP envelope, termination, optional size
policy, and IfcOpenShell parsing. Schema validation uses `ifcopenshell.validate` with
EXPRESS rules where the installed version supports them.

Targeted checks confirm repaired contexts are present and reference context entities.
Semantic snapshots compare schema, counts by class, all available GlobalIds, total
representation items, file sizes, hashes, and target assignments. Raw STEP line order
and IDs are not treated as semantic identity.

Pre-existing errors remain in the before report. After errors are retained, never
suppressed. Normalized issue keys classify resolved, unchanged, and newly introduced
issues. Newly introduced errors fail the CLI validation result; targeted semantic
change-control errors prevent the atomic output rename.

An optional geometry call is diagnostic only. External hooks should implement a small
adapter returning tool name, version, command/service identity, duration, exit status,
and structured messages. No CORENET X or IFC+SG pass claim is made without such a run.
