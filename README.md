# IFC+SG Repair Tool

A browser tool that checks IFC+SG files exported from Autodesk Revit 2025 and 2026
before they are submitted to CORENET X. It repairs two known export problems and
reports the rooms and areas that must be fixed in Revit.

**Open the tool:** https://noddlesskcho.github.io/IFC-Repair-Studio/

The IFC files are processed on your own computer, in the browser tab. They are not
uploaded or stored anywhere. The version and release date are shown at the bottom
of the page.

## How to use

1. Open the tool and drop one or more `.ifc` files on the page, or click
   **Choose IFC files**. Files must be IFC4.
2. Review the results. Each kind of issue has its own list, which you can open
   with **Show list**. When you check several files, you can filter the lists by
   file.
3. Click **Repair all files**. The tool repairs a copy of each file and checks
   the result.
4. Click **Download all files (.zip)**. The ZIP holds the repaired IFC files and,
   if any were found, the Areas without geometry report (Excel).

Your original files are never changed.

## What the tool checks

| Check | What the tool does |
|---|---|
| Missing geometry context (`IfcShapeRepresentation.ContextOfItems = $`) | Repairs it. It adds the link to the model's only matching context. Nothing is deleted. |
| Empty 3D shapes (`IfcClosedShell` with no faces) | Repairs it. It deletes only the empty shape; the element keeps its name, Revit ID, properties and level. Check these elements in Revit first. |
| Areas without geometry (`IfcSpace.Representation = $`) | Report only. Lists each room or area with its Revit Lookup ID, the reason it has no shape, and how to fix it in Revit. |
| File is not IFC4 (for example IFC2X3) | Blocks the file. CORENET X accepts IFC4 only. The IFC schema box turns red. |

This tool is not a complete IFC validator or CORENET X compliance checker. A
repaired IFC should still go through the normal submission validation.

### Missing geometry context

Each shape must name the view it belongs to: the 3D model (`Body`) or the 2D plan
outline (`FootPrint`). The tool repairs `Body / SweptSolid`, `Body / Tessellation`
and `FootPrint / Curve2D` shapes when exactly one compatible, project-connected
context exists. It checks every `IfcShapeRepresentation`, including those used by
`IfcProductDefinitionShape`, `IfcShapeAspect`, presentation layers and
`IfcRepresentationMap`. Only the missing attribute is replaced. When no context,
or more than one, matches, the shape is reported and not changed.

### Empty IfcClosedShell geometry

Revit can export an `IfcFacetedBrep` whose outer shell has no faces:
`IFCCLOSEDSHELL(());`. `IfcClosedShell.CfsFaces` is `SET [1:?] OF IfcFace`, so the
file is invalid IFC4, and the portal can stop processing the model. The tool
removes:

- the empty `IfcClosedShell` and the `IfcFacetedBrep` that wraps it;
- the brep reference in `IfcShapeRepresentation.Items`, and any `IfcStyledItem`
  or presentation layer entry that points at the brep;
- a representation left with no items, its reference in
  `IfcProductDefinitionShape` and presentation layers, and a product shape or
  layer assignment left empty (all of these lists are `[1:?]`);
- for a product whose only shape was empty, `Representation` is set to `$`
  (the attribute is optional). No element is deleted.

A shell or brep used in any other way (for example by `IfcShellBasedSurfaceModel`,
an `IfcRepresentationMap` or `IfcShapeAspect`, or another representation) is
reported and not changed. A representation that also misses its `ContextOfItems`
gets its context repaired first; check the repaired file again to remove its empty
geometry.

### Areas without geometry (report only)

Every `IfcSpace` (Revit room, space or area) whose `Representation` is `$` is
listed with its number, name, level, GUID and Revit Lookup ID (from
`IfcSpaceType.Tag`). The IFC has no correct outline for these spaces, so the tool
does not change them. The "Why no geometry" reason is read from the space's
`Qto_SpaceBaseQuantities` area and height:

- **Has area, but Revit could not build the 3D shape:** the room is placed and
  enclosed, but its boundary could not be turned into a 3D shape, for example
  because of very short or overlapping boundary lines, slivers or gaps;
- **Area is 0:** the room or area is not enclosed, or it is redundant;
- **Has area but height is 0:** the upper limit is at or below the base;
- **No area data in the IFC:** base quantities were not exported, so the cause
  cannot be read from the file.

The Excel report is named `<file>_Areas_without_geometry.xlsx`, or
`IFC-SG_Areas_without_geometry.xlsx` for several files. Download it from the
results, or take it from the repaired ZIP. In Revit, find each row with
**Manage > Select by ID** and the Revit Lookup ID.

### How the repair is verified

The output is built from slices of the original file plus the planned edits.
Before the download is offered, the tool reads the repaired file again and
confirms that:

- every planned edit was made, and nothing else changed;
- no remaining record references a removed record;
- no supported issue remains.

## Browser and file limits

- Use a current desktop Microsoft Edge, Google Chrome, Firefox or Safari.
- Input must be uncompressed `.ifc`. ZIP and IFCZIP input are not supported.
- Files are read as a stream, but very large files are limited by the browser's
  memory. A 650 MB file takes about 1 to 3 minutes to check and repair.

## Privacy

- There is no upload endpoint and no backend.
- There is no analytics, telemetry, cookie or external CDN.
- A file leaves the browser only when you download the result or share it
  yourself.

## For developers

The tool is plain HTML, CSS and JavaScript in `index.html`, `css/` and `js/`.
Node.js 20 or newer is used only for tests and the build. The live site does not
use Node.js or any server.

| Path | Purpose |
|---|---|
| `js/ifc-loader.js` | Streams the IFC, blocks non-IFC4 files, captures the records the checks need |
| `js/ifc-analyzer.js` | Missing-context check, links each issue to its element |
| `js/ifc-empty-shells.js` | Empty `IfcClosedShell` analysis and repair plan |
| `js/ifc-spaces.js` | Areas without geometry and the "Why no geometry" reason |
| `js/ifc-fixer.js` | Applies the edits and verifies the repaired file |
| `js/area-report.js` | Builds the Areas without geometry Excel report |
| `js/ifc-batch.js` | Combines results from several files, pagination |
| `js/zip-exporter.js`, `js/ifc-exporter.js` | Build the download ZIP and file names |
| `js/ui.js`, `js/app.js` | Page rendering and workflow |
| `tests/browser/` | Tests and small IFC fixtures |

### Run locally

A web server is needed, because browsers do not load JavaScript modules from a
file opened directly. From the repository root:

```powershell
npx serve .
```

Then open the URL that it prints. Any other static file server also works.

### Test and build

```powershell
npm test         # runs the tests in tests/browser
npm run build    # copies index.html, css/ and js/ into web-dist/
```

### Publish

Push to `main`. The workflow `.github/workflows/deploy-pages.yml`
(**Deploy IFC+SG Repair Tool**) runs the tests, builds `web-dist/` and updates
the live site in about a minute. If the tests fail, the live site is not changed.
Check progress under **Actions** in the repository.

### Release a new version

Change these together in one commit:

1. The footer line `Version x.y · d Mon yyyy` in `index.html`.
2. `version` in `package.json`.
3. Every `?v=x.y` query string in `index.html` and `js/*.js`. Browsers cache the
   CSS and JavaScript files, so a new query string makes them load the new files.
