# User guide

1. Start `ifc-context-repair-gui` and select or drop one `.ifc` file.
2. Click **Scan** and review the impacted IfcSlab representation summary.
3. If repairs are available, review the proposed output and click the blue **Repair N
   Representations** action.
4. Recommended mode writes `<name>_repaired.ifc`; the original remains unchanged.
   Advanced overwrite mode creates `<name>.original.ifc` and requires a dedicated
   confirmation.
5. Review the completion summary: file, location, successful repairs, and targeted
   slab issues remaining. A concise PDF executive report and a complete offline HTML
   engineering report are written beside the IFC automatically. CSV and JSON are
   available only from the HTML report's export controls. Debug logs are disabled by
   default.
6. Fast targeted verification is the default. Select full IFC schema validation only
   when needed; it may take significantly longer for large files.
7. Test the output with the applicable CORENET X and IFC+SG tools.

Only shape representations directly owned through `IfcSlab.Representation ->
IfcProductDefinitionShape.Representations` are in scope. Other product classes, mapped
representations, and shape aspects are ignored.

For automation, use the CLI examples in the project README. `--mode targeted` preserves
source formatting and is intended for controlled fallback use, not as a different
context-selection method.

Never send confidential IFC fixtures to a public repository. To anonymise a fixture,
work on a copy; replace names/descriptions/tags/owner and header paths; regenerate
GlobalIds only when cross-file matching is not under test; remove unrelated products;
reopen and validate; then manually inspect strings for project/client/location data.
Keep the original and the anonymisation mapping in restricted storage.
