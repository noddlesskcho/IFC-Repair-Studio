# IFC Fixer

IFC Fixer includes a static Browser Edition for private, local IFC4 inspection
and targeted repair, plus the existing Windows desktop application for the full
IFC+SG workflow.

The Browser Edition runs entirely from HTML, CSS, and JavaScript. An IFC selected
in the page is read through the browser File API, processed on the user's device,
and returned as a downloadable `Blob`. It is not uploaded to this project or to
another service.

## Run locally

No installation or production backend is required. From the repository root,
serve the files with any static server:

```powershell
python -m http.server 8000
```

Then open `http://localhost:8000/`. Python is only acting as a local static file
server here; it is not used by the web application.

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

This creates `web-dist/`. The separate name is intentional: this repository's
existing `dist/` directory is reserved for Windows/PyInstaller releases.
`web-dist/` contains only deployable static files and can be served by any basic
HTTP server.

Node.js is a development/build tool only. The production site does not require
Node.js, Python, Flask, FastAPI, Express, or any server-side application.

## Deploy to GitHub Pages

The workflow at `.github/workflows/deploy-pages.yml` tests, builds, uploads, and
deploys the site with the official GitHub Pages actions.

1. Push the repository to GitHub with `main` as the default branch.
2. Open **Settings > Pages** in the repository.
3. Under **Build and deployment**, select **GitHub Actions** as the source.
4. Open **Actions** and run **Deploy IFC Fixer to GitHub Pages**, or push a
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
- IFC4 schema;
- directly owned `IfcProductDefinitionShape` representations;
- missing `IfcShapeRepresentation.ContextOfItems`;
- `Body / SweptSolid` with one uniquely compatible, project-connected context;
- same-file sibling/peer evidence or the validated Revit slab pattern;
- byte-preserving, variable-length replacement of only the first representation
  attribute.

`Body / Tessellation` and `FootPrint / Curve2D` are detected but remain
report-only in the browser until their production compatibility policy is
approved. `IfcShapeAspect`, `IfcRepresentationMap`, ZIP/IFCZIP input, PDF/HTML
engineering reports, IfcOpenShell schema validation, and geometry-engine checks
remain desktop-only.

The original IFC object is never modified. The output is assembled from slices
of the original file plus the selected replacement tokens, then target records
and the STEP footer are verified before download is enabled.

## Browser compatibility

Use a current desktop version of Microsoft Edge, Google Chrome, Firefox, or
Safari with support for JavaScript modules, `Blob`, `File.stream()`,
`TextDecoder`, and `URL.createObjectURL`.

Large-file processing is streaming-first, but browser memory and Blob limits
vary by browser and operating system. The desktop application remains the
recommended option for very large models and full semantic validation.

## Privacy

- No IFC upload endpoint exists.
- No backend API call is made.
- No analytics, telemetry, cookie, or external CDN is included.
- Processing occurs locally in the active browser tab.
- A file leaves the browser only when the user explicitly downloads the repaired
  IFC or otherwise shares it.

## Desktop application

The Python/PySide6 application remains under `src/ifc_context_repair/`. It uses
IfcOpenShell and ReportLab for richer audits, reports, ZIP handling, optional
full schema validation, diagnostics, and the packaged Windows workflow. The web
conversion does not remove or silently reduce those desktop features.

See [the static conversion audit](docs/static-web-audit.md) for the exact
dependency and capability mapping.

> IFC Fixer performs targeted repairs for known IFC+SG export issues. It is not
> a complete IFC validator or CORENET X compliance checker. A repaired IFC
> should still undergo the normal submission validation process.
