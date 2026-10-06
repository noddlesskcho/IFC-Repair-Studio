# IFC+SG Repair Tool

IFC+SG Repair Tool is a static browser application for
private, local IFC4 inspection and targeted repair.

The Browser Edition runs entirely from HTML, CSS, and JavaScript. An IFC selected
in the page is read through the browser File API, processed on the user's device,
and returned as a downloadable `Blob`. It is not uploaded to this project or to
another service.

One or more IFC files can be selected or dropped together. Files are analyzed and
repaired sequentially to keep peak browser memory practical. The complete issue
table is collapsed by default and can be filtered by file; it shows 20 issues per
page in a five-row scrolling viewport. When requested, all repaired IFCs are
packaged locally into one ZIP download with visible progress.

## Run locally

No installation or production backend is required. From the repository root,
serve the files with any static server:

```powershell
npx serve .
```

Then open the URL that the server prints. Any other static file server also works.

If Node.js 20 or newer is available, the browser regression tests and static
build can be run with:

```powershell
npm test
npm run build
```

## Build static site

```powershell
npm run build
```

This creates `web-dist/`, which contains only deployable static files and can be
served by any basic HTTP server.

Node.js is a development/build tool only. The production site does not require
Node.js or any server-side application.

## Deploy to GitHub Pages

The workflow at `.github/workflows/deploy-pages.yml` tests, builds, uploads, and
deploys the site with the official GitHub Pages actions.

1. Push the repository to GitHub with `main` as the default branch.
2. Open **Settings > Pages** in the repository.
3. Under **Build and deployment**, select **GitHub Actions** as the source.
4. Open **Actions** and run **Deploy IFC+SG Repair Tool**, or push a
   commit to `main`.
5. Wait for both the `build` and `deploy` jobs to complete.

The resulting URL format is:

```text
https://USERNAME.github.io/REPOSITORY/
```

All application paths are repository-relative, so the site works under that
subdirectory without redirects or history routing.

## Supported IFC fixes

Browser production repair is deliberately narrow:

- uncompressed `.ifc` input;
- IFC4 schema only. CORENET X does not accept other schemas, so a file with any
  other `FILE_SCHEMA` (for example IFC2X3) is blocked as soon as its header is
  read, and the results show a red IFC schema box with a note;
- all `IfcShapeRepresentation` entities, including representations referenced by
  `IfcProductDefinitionShape`, `IfcShapeAspect`, presentation layer assignments,
  and `IfcRepresentationMap`;
- missing `IfcShapeRepresentation.ContextOfItems`;
- `Body / SweptSolid`, `Body / Tessellation`, and `FootPrint / Curve2D`;
- exactly one compatible, project-connected representation context;
- byte-preserving, variable-length replacement of only the first representation
  attribute.

### Empty IfcClosedShell geometry

Revit can export an `IfcFacetedBrep` whose outer shell has no faces:
`IFCCLOSEDSHELL(());`. `IfcClosedShell.CfsFaces` is `SET [1:?] OF IfcFace`, so
the file is invalid IFC4, and some viewers stop processing the model. The tool
removes this empty geometry:

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
report-only. A representation that also misses its `ContextOfItems` is repaired
for the context first; check the repaired file again to remove its empty geometry.
All empty-shell repairs in one file are applied together because they can share
records. After repair, the output is reread to confirm that the removed records
are gone and that no remaining record references them.

### Areas without geometry (report only)

Every `IfcSpace` (Revit room, space or area) whose `Representation` is `$` is
listed with its number, name, level, GUID and Revit Lookup ID (from
`IfcSpaceType.Tag`). The IFC has no correct outline for these spaces, so the tool
does not change them. A "Why no geometry" reason is read from the space's
`Qto_SpaceBaseQuantities` area and height:

- area and height present: Revit could not build the 3D shape from the room
  boundary (for example short or overlapping boundary lines, slivers or gaps);
- area 0: the room or area is not enclosed, or is redundant;
- area present but height 0: the upper limit is at or below the base;
- no base quantities: the cause cannot be read from the file.

The "Areas without geometry" Excel report (`<file>_Areas_without_geometry.xlsx`,
or `IFC-SG_Areas_without_geometry.xlsx` for several files) lists each space with
its reason and what to do in Revit. It can be downloaded from the results, and it
is also added to the repaired ZIP.

Ambiguous or missing compatible contexts remain report-only. ZIP/IFCZIP input,
PDF/HTML engineering reports, IfcOpenShell schema validation, and geometry-engine
checks are outside this static browser tool.

The original IFC object is never modified. The output is assembled from slices
of the original file plus the selected replacement tokens, then target records
and the STEP footer are verified before download is enabled.

## Browser compatibility

Use a current desktop version of Microsoft Edge, Google Chrome, Firefox, or
Safari with support for JavaScript modules, `Blob`, `File.stream()`,
`TextDecoder`, and `URL.createObjectURL`.

Large-file processing is streaming-first, but browser memory and Blob limits
vary by browser and operating system.

## Privacy

- No IFC upload endpoint exists.
- No backend API call is made.
- No analytics, telemetry, cookie, or external CDN is included.
- Processing occurs locally in the active browser tab.
- A file leaves the browser only when the user explicitly downloads the repaired
  IFC ZIP or otherwise shares it.

> IFC+SG Repair Tool performs targeted repairs for known IFC+SG export issues. It is not
> a complete IFC validator or CORENET X compliance checker. A repaired IFC
> should still undergo the normal submission validation process.
