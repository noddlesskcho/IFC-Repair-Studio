import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {fileURLToPath} from "node:url";

import {analyzeIfc} from "../../js/ifc-analyzer.js";
import {applyRepairs, verifyRepairs} from "../../js/ifc-fixer.js";
import {loadIfc, splitStepArguments} from "../../js/ifc-loader.js";
import {downloadBlob, repairedFileName} from "../../js/ifc-exporter.js";

const fixturePath = fileURLToPath(new URL("./fixtures/direct-missing-context.ifc", import.meta.url));

async function fixtureFile() {
  const bytes = await readFile(fixturePath);
  const blob = new Blob([bytes], {type: "application/x-step"});
  Object.defineProperty(blob, "name", {value: "direct-missing-context.ifc"});
  return blob;
}

test("STEP argument splitting preserves nested lists and quoted commas", () => {
  assert.deepEqual(splitStepArguments("$,'Body, Main','SweptSolid',(#1,#2)"), ["$", "'Body, Main'", "'SweptSolid'", "(#1,#2)"]);
});

test("browser pipeline detects, repairs, and verifies one direct representation", async () => {
  const source = await fixtureFile();
  const original = new Uint8Array(await source.arrayBuffer());
  const model = await loadIfc(source);
  const analysis = await analyzeIfc(model);

  assert.equal(model.schema, "IFC4");
  assert.equal(analysis.issues.length, 1);
  assert.equal(analysis.repairable, 1);
  assert.equal(analysis.issues[0].id, 300);
  assert.equal(analysis.issues[0].candidateContextId, 11);

  const {output, repairs} = await applyRepairs(source, analysis.issues);
  const verification = await verifyRepairs(source, output, repairs);
  assert.equal(verification.repaired, 1);
  assert.equal(verification.unexpectedChanges, 0);
  assert.match(await output.text(), /#300=IFCSHAPEREPRESENTATION\(#11,'Body','SweptSolid'/);
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
