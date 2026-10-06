import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {fileURLToPath} from "node:url";

import {analyzeIfc} from "../../js/ifc-analyzer.js";
import {combineAnalyses} from "../../js/ifc-batch.js";
import {loadIfc} from "../../js/ifc-loader.js";
import {decodeStepText} from "../../js/ifc-spaces.js";
import {areaAction, areaReportName, buildAreaReport} from "../../js/area-report.js";

async function fixture(name) {
  const bytes = await readFile(fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url)));
  const blob = new Blob([bytes], {type: "application/x-step"});
  Object.defineProperty(blob, "name", {value: name});
  return blob;
}

function ifcFile(records, name = "synthetic.ifc") {
  const blob = new Blob([`ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Test'),'2;1');
FILE_NAME('${name}','2026-10-06T00:00:00',(),(),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
${records}
ENDSEC;
END-ISO-10303-21;
`], {type: "application/x-step"});
  Object.defineProperty(blob, "name", {value: name});
  return blob;
}

// Reads the stored (uncompressed) entries of a ZIP produced by storedZip.
function zipEntries(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const entries = new Map();
  let offset = 0;
  while (view.getUint32(offset, true) === 0x04034b50) {
    const size = view.getUint32(offset + 18, true);
    const nameLength = view.getUint16(offset + 26, true);
    const name = new TextDecoder().decode(bytes.subarray(offset + 30, offset + 30 + nameLength));
    const start = offset + 30 + nameLength;
    entries.set(name, new TextDecoder().decode(bytes.subarray(start, start + size)));
    offset = start + size;
  }
  return entries;
}

test("IfcSpace without Representation is found with level and Revit Lookup ID", async () => {
  const analysis = await analyzeIfc(await loadIfc(await fixture("space-missing-representation.ifc")));
  const spaces = analysis.spaces;

  assert.equal(spaces.spaceCount, 3);
  assert.equal(spaces.issues.length, 2);
  assert.deepEqual(spaces.issues.map(space => space.number), ["206", "242"]);
  assert.equal(spaces.issues[0].name, "Hardscape (A)");
  assert.equal(spaces.issues[0].level, "Level 01");
  assert.equal(spaces.issues[0].levelMethod, "IfcRelContainedInSpatialStructure");
  assert.equal(spaces.issues[0].predefinedType, "USERDEFINED");
  assert.equal(spaces.issues[0].objectType, "AREA_GFA");
  assert.equal(spaces.issues[0].guid, "2gtOLZW611seK_EDC_KbnA");
  assert.equal(spaces.issues[0].revitId, "1681744");
  assert.equal(spaces.issues[1].level, "Level 02");
  assert.equal(spaces.issues[1].levelMethod, "HierarchyTraversal");
  assert.equal(spaces.issues[1].guid, "34OgwEfZb9JPkg2Uwg8Zt$");
  assert.equal(spaces.issues[1].revitId, "7654321");
});

test("Revit Lookup ID comes from IfcSpaceType.Tag", async () => {
  const analysis = await analyzeIfc(await loadIfc(await fixture("space-type-tag-revit-id.ifc")));

  assert.equal(analysis.spaces.issues.length, 1);
  assert.equal(analysis.spaces.issues[0].stepId, 67);
  assert.equal(analysis.spaces.issues[0].number, "43");
  assert.equal(analysis.spaces.issues[0].name, "Hydrant Tank");
  assert.equal(analysis.spaces.issues[0].revitId, "1681744");
});

test("a relationship longer than the 64 KB capture still links its spaces to the storey", async () => {
  const fillers = Array.from({length: 12000}, (_, index) => `#${100000 + index}`).join(",");
  const model = await loadIfc(ifcFile(`#1=IFCBUILDINGSTOREY('0STOREY000000000000000',$,'Level 07',$,$,$,$,$,.ELEMENT.,0.);
#2=IFCSPACE('0SPACE0000000000000000',$,'701',$,$,$,$,'Plant Room',.ELEMENT.,.INTERNAL.,$);
#3=IFCRELAGGREGATES('0REL000000000000000000',$,$,$,#1,(${fillers},#2));
#4=IFCSPACETYPE('0TYPE000000000000000000',$,'Room',$,$,$,$,'998877',$,.SPACE.,$);
#5=IFCRELDEFINESBYTYPE('0RELTYPE00000000000000',$,$,$,(${fillers},#2),#4);`));
  const analysis = await analyzeIfc(model);

  assert.equal(analysis.spaces.issues.length, 1);
  assert.equal(analysis.spaces.issues[0].level, "Level 07");
  assert.equal(analysis.spaces.issues[0].name, "Plant Room");
  assert.equal(analysis.spaces.issues[0].revitId, "998877");
});

test("IFC escaped text is decoded for the report", () => {
  assert.equal(decodeStepText("Caf\\X\\E9 \\X2\\5BA48F69\\X0\\"), "Café 室轩");
});

test("combined analysis carries space issues per file and the Excel report lists them", async () => {
  const entries = [];
  for (const name of ["space-missing-representation.ifc", "space-type-tag-revit-id.ifc"]) {
    const file = await fixture(name);
    entries.push({file, analysis: await analyzeIfc(await loadIfc(file)), error: null});
  }
  const combined = combineAnalyses(entries);

  assert.equal(combined.spaceIssues.length, 3);
  assert.equal(combined.spacesScanned, 3 + entries[1].analysis.spaces.spaceCount);
  assert.deepEqual(combined.files.map(file => file.spaceIssueCount), [2, 1]);
  assert.equal(areaReportName(combined), "IFC-SG_Areas_without_geometry.xlsx");
  assert.equal(areaReportName(combineAnalyses(entries.slice(0, 1))), "space-missing-representation_Areas_without_geometry.xlsx");

  const report = await buildAreaReport(combined);
  assert.equal(report.type, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  const parts = zipEntries(new Uint8Array(await report.arrayBuffer()));
  assert.ok(parts.has("[Content_Types].xml"));
  assert.match(parts.get("xl/workbook.xml"), /name="Areas without geometry".*name="How to use"/);
  const sheet = parts.get("xl/worksheets/sheet1.xml");
  for (const title of ["Revit Lookup ID", "Area", "Height", "Why no geometry", "What to do in Revit"]) {
    assert.match(sheet, new RegExp(`<t xml:space="preserve">${title}</t>`));
  }
  assert.match(sheet, /<t xml:space="preserve">Hardscape \(A\)<\/t>/);
  assert.match(sheet, /<t xml:space="preserve">1681744<\/t>/);
  assert.match(sheet, /<t xml:space="preserve">space-type-tag-revit-id.ifc<\/t>/);
  assert.equal((sheet.match(/<row /g) || []).length, 4);
});

test("Why no geometry is read from Revit base quantities", async () => {
  const space = (id, name) => `#${id}=IFCSPACE('0SPACE${id}00000000000000',$,'${name}',$,$,$,$,'${name}',.ELEMENT.,.NOTDEFINED.,$);`;
  const quantities = (id, spaceId, area, height) => `#${id}1=IFCQUANTITYAREA('GrossFloorArea','',$,${area},$);
#${id}2=IFCQUANTITYLENGTH('Height','',$,${height},$);
#${id}3=IFCELEMENTQUANTITY('0QTO${id}000000000000000',$,'Qto_SpaceBaseQuantities',$,$,(#${id}1,#${id}2));
#${id}4=IFCRELDEFINESBYPROPERTIES('0RDP${id}000000000000000',$,$,$,(#${spaceId}),#${id}3);`;
  const model = await loadIfc(ifcFile(`#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#2=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);
#3=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#4=IFCUNITASSIGNMENT((#1,#2));
#5=IFCPROJECT('0PROJECT00000000000000',$,'Test',$,$,$,$,$,#4);
${space(10, "A")}
${space(11, "B")}
${space(12, "C")}
${space(13, "D")}
${quantities(20, 10, "24.0183902", "4704.")}
${quantities(30, 11, "0.", "3000.")}
${quantities(40, 12, "12.5", "0.")}
#50=IFCRELSPACEBOUNDARY('0BND000000000000000000',$,'1stLevel',$,#10,$,$,.VIRTUAL.,.INTERNAL.);
#51=IFCRELSPACEBOUNDARY('0BND000000000000000001',$,'1stLevel',$,#10,$,$,.VIRTUAL.,.INTERNAL.);`));
  const byNumber = Object.fromEntries((await analyzeIfc(model)).spaces.issues.map(issue => [issue.number, issue]));

  assert.equal(byNumber.A.reason, "shapeFailed");
  assert.equal(byNumber.A.area, "24.02 m²");
  assert.equal(byNumber.A.height, "4,704 mm");
  assert.equal(byNumber.A.boundaries, 2);
  assert.match(byNumber.A.reasonLabel, /Has area, but Revit could not build the 3D shape/);
  assert.equal(byNumber.B.reason, "noArea");
  assert.equal(byNumber.C.reason, "noHeight");
  assert.equal(byNumber.D.reason, "noData");
  assert.equal(byNumber.D.area, "N/A");
  assert.match(areaAction(byNumber.D), /Room or Area schedule.*Export base quantities/);
});

test("a blocked IFC2X3 file is listed as a file error with its schema", async () => {
  const good = await fixture("space-type-tag-revit-id.ifc");
  const text = (await (await fixture("space-type-tag-revit-id.ifc")).text()).replace("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA(('IFC2X3'))");
  const bad = new Blob([text]);
  Object.defineProperty(bad, "name", {value: "old-export.ifc"});
  const entries = [{file: good, analysis: await analyzeIfc(await loadIfc(good)), error: null}];
  entries.push(await loadIfc(bad).then(() => assert.fail("IFC2X3 must be blocked"), error => ({file: bad, analysis: null, error})));
  const combined = combineAnalyses(entries);

  assert.deepEqual(combined.blockedSchemas, ["IFC2X3"]);
  assert.equal(combined.schema, "IFC4 / IFC2X3");
  assert.equal(combined.fileErrors[0].fileName, "old-export.ifc");
  assert.match(combined.fileErrors[0].message, /CORENET X does not support IFC2X3/);
});
