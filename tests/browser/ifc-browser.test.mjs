import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {fileURLToPath} from "node:url";

import {analyzeIfc} from "../../js/ifc-analyzer.js";
import {applyRepairs, verifyRepairedModel, verifyRepairs} from "../../js/ifc-fixer.js";
import {loadIfc, splitStepArguments} from "../../js/ifc-loader.js";
import {downloadBlob, repairedFileName} from "../../js/ifc-exporter.js";

const fixturePath = fileURLToPath(new URL("./fixtures/direct-missing-context.ifc", import.meta.url));

async function fixtureFile() {
  const bytes = await readFile(fixturePath);
  const blob = new Blob([bytes], {type: "application/x-step"});
  Object.defineProperty(blob, "name", {value: "direct-missing-context.ifc"});
  return blob;
}

function ifcFile(records, name = "synthetic.ifc") {
  const text = `ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Test'),'2;1');
FILE_NAME('${name}','2026-09-09T00:00:00',(),(),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
${records}
ENDSEC;
END-ISO-10303-21;
`;
  const blob = new Blob([text], {type: "application/x-step"});
  Object.defineProperty(blob, "name", {value: name});
  return blob;
}

const modelContext = `#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#20,$);
#11=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#10,$,.MODEL_VIEW.,$);
#12=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('FootPrint','Model',*,*,*,*,#10,$,.MODEL_VIEW.,$);
#20=IFCAXIS2PLACEMENT3D(#21,$,$);
#21=IFCCARTESIANPOINT((0.,0.,0.));
#30=IFCPROJECT('0PROJECT00000000000000',$,'Test',$,$,$,$,(#10),$);`;

test("STEP argument splitting preserves nested lists and quoted commas", () => {
  assert.deepEqual(splitStepArguments("$,'Body, Main','SweptSolid',(#1,#2)"), ["$", "'Body, Main'", "'SweptSolid'", "(#1,#2)"]);
});

test("browser pipeline repairs direct Body and FootPrint representations", async () => {
  const source = await fixtureFile();
  const original = new Uint8Array(await source.arrayBuffer());
  const model = await loadIfc(source);
  const analysis = await analyzeIfc(model);

  assert.equal(model.schema, "IFC4");
  assert.equal(analysis.issues.length, 2);
  assert.equal(analysis.repairable, 2);
  assert.equal(analysis.issues[0].id, 300);
  assert.equal(analysis.issues[0].candidateContextId, 11);
  assert.equal(analysis.issues[1].id, 302);
  assert.equal(analysis.issues[1].candidateContextId, 12);

  const {output, repairs} = await applyRepairs(source, analysis.issues);
  const verification = await verifyRepairs(source, output, repairs);
  assert.equal(verification.repaired, 2);
  assert.equal(verification.unexpectedChanges, 0);
  assert.match(await output.text(), /#300=IFCSHAPEREPRESENTATION\(#11,'Body','SweptSolid'/);
  assert.match(await output.text(), /#302=IFCSHAPEREPRESENTATION\(#12,'FootPrint','Curve2D'/);
  assert.deepEqual(new Uint8Array(await source.arrayBuffer()), original, "source IFC must remain unchanged");
});

test("unsupported schema is audited without repair proposals", async () => {
  const source = await fixtureFile();
  const text = (await source.text()).replace("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA(('IFC2X3'))");
  const blob = new Blob([text]);
  Object.defineProperty(blob, "name", {value: "unsupported.ifc"});
  const analysis = await analyzeIfc(await loadIfc(blob));
  assert.equal(analysis.schema, "IFC2X3");
  assert.equal(analysis.issues.length, 0);
});

test("download exporter uses a local Blob URL and repaired filename", () => {
  assert.equal(repairedFileName("Project.IFC"), "Project_repaired.ifc");
  const originalDocument = globalThis.document;
  const originalSetTimeout = globalThis.setTimeout;
  let clicked = false;
  let appended = false;
  let downloadName = null;
  globalThis.document = {
    body: {append() { appended = true; }},
    createElement() {
      return {
        style: {},
        set download(value) { downloadName = value; },
        set href(_value) {},
        click() { clicked = true; },
        remove() {},
      };
    },
  };
  globalThis.setTimeout = callback => { callback(); return 1; };
  try {
    downloadBlob(new Blob(["IFC"]), "Project_repaired.ifc");
  } finally {
    globalThis.document = originalDocument;
    globalThis.setTimeout = originalSetTimeout;
  }
  assert.equal(appended, true);
  assert.equal(clicked, true);
  assert.equal(downloadName, "Project_repaired.ifc");
});

for (const [label, identifier, representationType, contextId] of [
  ["Body SweptSolid", "Body", "SweptSolid", 11],
  ["Body Tessellation", "Body", "Tessellation", 11],
  ["FootPrint Curve2D", "FootPrint", "Curve2D", 12],
]) {
  test(`${label} is repairable with one compatible context`, async () => {
    const source = ifcFile(`${modelContext}
#100=IFCSHAPEREPRESENTATION($,'${identifier}','${representationType}',(#200));
#200=IFCGEOMETRICSET(());
`);
    const analysis = await analyzeIfc(await loadIfc(source));
    assert.equal(analysis.issues.length, 1);
    assert.equal(analysis.repairable, 1);
    assert.equal(analysis.issues[0].candidateContextId, contextId);
    const {output, repairs} = await applyRepairs(source, analysis.issues);
    await verifyRepairs(source, output, repairs);
    Object.defineProperty(output, "name", {value: "repaired.ifc"});
    const outputModel = await loadIfc(output);
    assert.equal(verifyRepairedModel(outputModel, repairs).successfulChanges, 1);
    assert.match(await output.text(), new RegExp(`#100=IFCSHAPEREPRESENTATION\\(#${contextId},'${identifier}','${representationType}'`));
  });
}

test("ShapeAspect-owned Body SweptSolid is detected and repairable", async () => {
  const source = ifcFile(`${modelContext}
#100=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#200));
#300=IFCPRODUCTDEFINITIONSHAPE($,$,());
#400=IFCSHAPEASPECT((#100),'Aspect',$,.T.,#300);
#401=IFCPRESENTATIONLAYERASSIGNMENT('Layer',$,(#100),$);
#500=IFCWALL('0WALL000000000000000000',$,'Test wall',$,$,#501,#300,$,$);
#200=IFCGEOMETRICSET(());
`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.repairable, 1);
  assert.deepEqual(analysis.issues[0].referencedBy, ["IfcShapeAspect", "IfcPresentationLayerAssignment"]);
  assert.equal(analysis.issues[0].productType, "IfcWall");
  assert.equal(analysis.issues[0].productName, "Test wall");
});

test("ShapeAspect-owned Body Tessellation is detected and repairable", async () => {
  const source = ifcFile(`${modelContext}
#100=IFCSHAPEREPRESENTATION($,'Body','Tessellation',(#200));
#300=IFCPRODUCTDEFINITIONSHAPE($,$,());
#400=IFCSHAPEASPECT((#100),'Aspect',$,.T.,#300);
#200=IFCTRIANGULATEDFACESET(#201,$,.T.,((1,2,3)),$);
`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.issues[0].signature, "body|tessellation");
  assert.equal(analysis.issues[0].repairable, true);
});

test("two compatible Body contexts require review", async () => {
  const source = ifcFile(`${modelContext}
#13=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#10,$,.MODEL_VIEW.,$);
#100=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#200));
#200=IFCGEOMETRICSET(());
`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.issues[0].repairable, false);
  assert.equal(analysis.issues[0].status, "Review Required");
  assert.match(analysis.issues[0].reason, /2 compatible/);
});

test("FootPrint PLAN_VIEW and MODEL_VIEW contexts require review", async () => {
  const source = ifcFile(`${modelContext}
#13=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('FootPrint','Model',*,*,*,*,#10,$,.PLAN_VIEW.,$);
#100=IFCSHAPEREPRESENTATION($,'FootPrint','Curve2D',(#200));
#200=IFCGEOMETRICSET(());
`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.issues[0].repairable, false);
  assert.equal(analysis.issues[0].status, "Review Required");
  assert.match(analysis.issues[0].reason, /2 compatible/);
});

test("missing compatible context is not repairable", async () => {
  const source = ifcFile(`#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#20,$);
#20=IFCAXIS2PLACEMENT3D(#21,$,$);
#21=IFCCARTESIANPOINT((0.,0.,0.));
#30=IFCPROJECT('0PROJECT00000000000000',$,'Test',$,$,$,$,(#10),$);
#100=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#200));
#200=IFCGEOMETRICSET(());
`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.issues[0].repairable, false);
  assert.equal(analysis.issues[0].status, "No Compatible Context");
});

test("representation with an existing legal context is not an issue", async () => {
  const source = ifcFile(`${modelContext}
#100=IFCSHAPEREPRESENTATION(#11,'Body','SweptSolid',(#200));
#200=IFCGEOMETRICSET(());
`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.issues.length, 0);
});

test("repair leaves unrelated optional dollar tokens unchanged", async () => {
  const source = ifcFile(`${modelContext}
#40=IFCOWNERHISTORY($,$,$,.ADDED.,$,$,$,0);
#100=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#200));
#200=IFCGEOMETRICSET(());
`);
  const analysis = await analyzeIfc(await loadIfc(source));
  const {output, repairs} = await applyRepairs(source, analysis.issues);
  assert.equal(repairs.length, 1);
  assert.match(await output.text(), /#40=IFCOWNERHISTORY\(\$,\$,\$,.ADDED.,\$,\$,\$,0\);/);
});
