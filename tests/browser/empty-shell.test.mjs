import assert from "node:assert/strict";
import test from "node:test";

import {analyzeIfc} from "../../js/ifc-analyzer.js";
import {applyRepairs, verifyNoDanglingReferences, verifyRepairedModel, verifyRepairs} from "../../js/ifc-fixer.js";
import {loadIfc} from "../../js/ifc-loader.js";

function ifcFile(records, name = "empty-shell.ifc") {
  const lines = [
    "ISO-10303-21;", "HEADER;", "FILE_DESCRIPTION(('Test'),'2;1');",
    `FILE_NAME('${name}','2026-09-28T00:00:00',(),(),'','','');`, "FILE_SCHEMA(('IFC4'));", "ENDSEC;", "DATA;",
    ...records.trim().split("\n"), "ENDSEC;", "END-ISO-10303-21;", "",
  ];
  const blob = new Blob([lines.join("\r\n")], {type: "application/x-step"});
  Object.defineProperty(blob, "name", {value: name});
  return blob;
}

const base = `#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#20,$);
#11=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#10,$,.MODEL_VIEW.,$);
#20=IFCAXIS2PLACEMENT3D(#21,$,$);
#21=IFCCARTESIANPOINT((0.,0.,0.));
#30=IFCPROJECT('0PROJECT00000000000000',$,'Test',$,$,$,$,(#10),$);
#40=IFCLOCALPLACEMENT($,#20);
#50=IFCPOLYLOOP((#21,#21,#21));
#51=IFCFACEOUTERBOUND(#50,.T.);
#52=IFCFACE((#51));
#60=IFCSURFACESTYLE('Glass',.BOTH.,());`;

// Revit louver pattern: every Body item is an IfcFacetedBrep around IFCCLOSEDSHELL(()).
const louver = `${base}
#100=IFCCLOSEDSHELL(());
#101=IFCFACETEDBREP(#100);
#102=IFCCLOSEDSHELL(());
#103=IFCFACETEDBREP(#102);
#104=IFCSTYLEDITEM(#101,(#60),$);
#110=IFCSHAPEREPRESENTATION(#11,'Body','Brep',(#101,#103));
#111=IFCPRODUCTDEFINITIONSHAPE($,$,(#110));
#112=IFCSHADINGDEVICE('3ZEdFlJ3p0Wgv8suCk$gCR',$,'Sloped Glazing:Louver:985751',$,'Sloped Glazing:Louver',#40,#111,'985751',.USERDEFINED.);
#113=IFCPRESENTATIONLAYERASSIGNMENT('A-GLAZ',$,(#110),$);`;

// Curtain wall panel pattern: a few empty breps among real geometry.
const panel = `${base}
#200=IFCCLOSEDSHELL(());
#201=IFCFACETEDBREP(#200);
#202=IFCCLOSEDSHELL((#52));
#203=IFCFACETEDBREP(#202);
#210=IFCSHAPEREPRESENTATION(#11,'Body','Brep',(#201,#203));
#211=IFCPRODUCTDEFINITIONSHAPE($,$,(#210));
#212=IFCCOVERING('12DQx$oWulOrJZ_ULZbCcw',$,'Curtain Wall:WT72:1076467 #201',$,'SANDWICHPANEL',#40,#211,'1076467',.CLADDING.);
#213=IFCPRESENTATIONLAYERASSIGNMENT('A-WALL',$,(#201,#203),$);`;

async function repairAll(source) {
  const analysis = await analyzeIfc(await loadIfc(source));
  const {output, repairs, edits} = await applyRepairs(source, analysis.issues.filter(issue => issue.selected));
  await verifyRepairs(source, output, repairs, () => {}, edits);
  Object.defineProperty(output, "name", {value: "repaired.ifc"});
  const outputModel = await loadIfc(output);
  verifyRepairedModel(outputModel, repairs);
  await verifyNoDanglingReferences(output, repairs);
  return {analysis, output, text: await output.text(), post: await analyzeIfc(outputModel)};
}

test("element whose only geometry is empty keeps its data with Representation $", async () => {
  const {analysis, text, post} = await repairAll(ifcFile(louver));
  assert.equal(analysis.counts.emptyClosedShell, 1);
  const [issue] = analysis.issues;
  assert.equal(issue.status, "Repairable");
  assert.equal(issue.productType, "IfcShadingDevice");
  assert.equal(issue.globalId, "3ZEdFlJ3p0Wgv8suCk$gCR");
  assert.equal(issue.proposedContext, "Remove empty representation");
  for (const id of [100, 101, 102, 103, 104, 110, 111, 113]) assert.doesNotMatch(text, new RegExp(`#${id}=`));
  assert.match(text, /#112=IFCSHADINGDEVICE\('3ZEdFlJ3p0Wgv8suCk\$gCR',\$,'Sloped Glazing:Louver:985751',\$,'Sloped Glazing:Louver',#40,\$,'985751',\.USERDEFINED\.\);/);
  assert.doesNotMatch(text, /\r\n\r\n/, "no blank lines are left behind");
  assert.equal(post.issues.length, 0);
});

test("empty items are removed and real geometry is kept", async () => {
  const {analysis, text, post} = await repairAll(ifcFile(panel));
  const [issue] = analysis.issues;
  assert.equal(issue.status, "Repairable");
  assert.equal(issue.proposedContext, "Remove 1 empty item; keep 1");
  assert.match(text, /#210=IFCSHAPEREPRESENTATION\(#11,'Body','Brep',\(#203\)\);/);
  assert.match(text, /#213=IFCPRESENTATIONLAYERASSIGNMENT\('A-WALL',\$,\(#203\),\$\);/);
  assert.match(text, /#212=IFCCOVERING\('12DQx\$oWulOrJZ_ULZbCcw',\$,'Curtain Wall:WT72:1076467 #201'/, "a #ref inside a name is left alone");
  assert.match(text, /#202=IFCCLOSEDSHELL\(\(#52\)\);/);
  assert.doesNotMatch(text, /#200=|#201=/);
  assert.equal(post.issues.length, 0);
});

test("shell used outside an IfcFacetedBrep requires review", async () => {
  const source = ifcFile(`${panel}
#220=IFCSHELLBASEDSURFACEMODEL((#200));`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.issues[0].status, "Review Required");
  assert.match(analysis.issues[0].reason, /used by more than its IfcFacetedBrep/);
  await assert.rejects(applyRepairs(source, analysis.issues), /Select at least one repairable issue/);
});

test("representation used by an IfcRepresentationMap is not emptied automatically", async () => {
  const source = ifcFile(`${louver}
#120=IFCREPRESENTATIONMAP(#20,#110);`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.issues[0].status, "Review Required");
  assert.match(analysis.issues[0].reason, /IFCREPRESENTATIONMAP/);
});

test("styled item that is referenced elsewhere blocks deletion", async () => {
  const source = ifcFile(`${louver}
#121=IFCPRESENTATIONLAYERWITHSTYLE('Style',$,(#104),$,.T.,.F.,.F.,());`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.issues[0].status, "Review Required");
  assert.match(analysis.issues[0].reason, /IfcStyledItem #104/);
});

test("representation that also misses its context is left for a second pass", async () => {
  // Revit writes the WT72 panel as Body / Tessellation holding IfcFacetedBrep items.
  const source = ifcFile(panel.replace("#210=IFCSHAPEREPRESENTATION(#11,'Body','Brep',", "#210=IFCSHAPEREPRESENTATION($,'Body','Tessellation',"));
  const analysis = await analyzeIfc(await loadIfc(source));
  const context = analysis.issues.find(issue => issue.issueType !== "emptyClosedShell");
  const shell = analysis.issues.find(issue => issue.issueType === "emptyClosedShell");
  assert.equal(context.status, "Repairable");
  assert.equal(shell.status, "Review Required");
  assert.match(shell.reason, /Repair the context first/);
});

test("empty-shell repairs sharing records must be applied together", async () => {
  const source = ifcFile(`${louver}
#130=IFCCLOSEDSHELL(());
#131=IFCFACETEDBREP(#130);
#132=IFCSHAPEREPRESENTATION(#11,'Body','Brep',(#131));
#133=IFCPRODUCTDEFINITIONSHAPE($,$,(#132));
#134=IFCSHADINGDEVICE('20JRaa0Q0Aiy72b$xPRfvT',$,'Sloped Glazing:Louver:995634',$,$,#40,#133,'995634',$);`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.equal(analysis.repairable, 2);
  await assert.rejects(applyRepairs(source, [analysis.issues[0]]), /must be repaired together/);
  const {post, text} = await repairAll(source);
  assert.equal(post.issues.length, 0);
  assert.match(text, /#134=IFCSHADINGDEVICE\('20JRaa0Q0Aiy72b\$xPRfvT',\$,'Sloped Glazing:Louver:995634',\$,\$,#40,\$,'995634',\$\);/);
});

test("repair stops when the file changed after analysis", async () => {
  const source = ifcFile(panel);
  const analysis = await analyzeIfc(await loadIfc(source));
  const changed = ifcFile(panel.replace("#200=IFCCLOSEDSHELL(());", "#200=IFCCLOSEDSHELL((#52));"));
  await assert.rejects(applyRepairs(changed, analysis.issues), /no longer empty|changed after analysis/);
});
