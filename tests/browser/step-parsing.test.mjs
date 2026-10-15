import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {fileURLToPath} from "node:url";

import {analyzeIfc} from "../../js/ifc-analyzer.js";
import {applyRepairs, verifyNoDanglingReferences, verifyRepairedModel, verifyRepairs} from "../../js/ifc-fixer.js";
import {IfcInputError, loadIfc} from "../../js/ifc-loader.js";
import {decodeStepText} from "../../js/ifc-spaces.js";

function ifcFile(records, {header = "", name = "step-parsing.ifc"} = {}) {
  const blob = new Blob([`ISO-10303-21;
${header}HEADER;
FILE_DESCRIPTION(('Test'),'2;1');
FILE_NAME('${name}','2026-10-15T00:00:00',(),(),'','','');
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

test("an entity after a comment on the same line is read", async () => {
  const model = await loadIfc(ifcFile(`/* leading comment */ #1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#2=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.); /* between */ #3=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
/* a comment
   over two lines */ #4=IFCUNITASSIGNMENT((#1,#2));`, {header: "/* exporter note, with 'quote' */\n"}));
  assert.deepEqual([...model.entities.keys()].sort((a, b) => a - b), [1, 2, 3, 4]);
});

test("a comment that opens with /*/ does not close on its own slash", async () => {
  const model = await loadIfc(ifcFile(`#1=IFCSIUNIT(*,.LENGTHUNIT.,/*/ odd; comment */$,.METRE.);
#2=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);`));
  assert.deepEqual([...model.entities.keys()], [1, 2]);
  assert.equal(model.spatial.units.get(1).name, "METRE", "the record is not cut at the ; inside the comment");
});

test("an unterminated comment between records is reported", async () => {
  await assert.rejects(loadIfc(ifcFile(`#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
/* never closed
#2=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);`)), IfcInputError);
});

test("a quantity link written before its Qto_SpaceBaseQuantities set is kept", async () => {
  const model = await loadIfc(ifcFile(`#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#2=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);
#4=IFCUNITASSIGNMENT((#1,#2));
#5=IFCPROJECT('0PROJECT00000000000000',$,'Test',$,$,$,$,$,#4);
#10=IFCSPACE('0SPACE1000000000000000',$,'A',$,$,$,$,'A',.ELEMENT.,.NOTDEFINED.,$);
#24=IFCRELDEFINESBYPROPERTIES('0RDP20000000000000000',$,$,$,(#10),#23);
#21=IFCQUANTITYAREA('GrossFloorArea','',$,24.0183902,$);
#22=IFCQUANTITYLENGTH('Height','',$,4704.,$);
#23=IFCELEMENTQUANTITY('0QTO20000000000000000',$,'Qto_SpaceBaseQuantities',$,$,(#21,#22));`));
  const [issue] = (await analyzeIfc(model)).spaces.issues;
  assert.equal(issue.reason, "shapeFailed");
  assert.equal(issue.area, "24.02 m²");
  assert.equal(issue.height, "4,704 mm");
});

test("a comment inside a repaired record does not shift the edited attribute", async () => {
  const source = ifcFile(`#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#20,$);
#11=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#10,$,.MODEL_VIEW.,$);
#20=IFCAXIS2PLACEMENT3D(#21,$,$);
#21=IFCCARTESIANPOINT((0.,0.,0.));
#30=IFCPROJECT('0PROJECT00000000000000',$,'Test',$,$,$,$,(#10),$);
#40=IFCLOCALPLACEMENT($,#20);
#50=IFCPOLYLOOP((#21,#21,#21));
#51=IFCFACEOUTERBOUND(#50,.T.);
#52=IFCFACE((#51));
#200=IFCCLOSEDSHELL(());
#201=IFCFACETEDBREP(#200);
#202=IFCCLOSEDSHELL((#52));
#203=IFCFACETEDBREP(#202);
#210=IFCSHAPEREPRESENTATION(#11,'Body','Brep',(#201,#203));
#211=IFCPRODUCTDEFINITIONSHAPE($,$,(#210));
#212=IFCCOVERING('12DQx$oWulOrJZ_ULZbCcw',$,'Panel',$,'SANDWICHPANEL',#40,#211,'1076467',.CLADDING.);
#213=IFCPRESENTATIONLAYERASSIGNMENT('A-WALL',/* note, (x */$,(#201,#203),$);`);
  const analysis = await analyzeIfc(await loadIfc(source));
  const {output, repairs, edits} = await applyRepairs(source, analysis.issues.filter(issue => issue.selected));
  await verifyRepairs(source, output, repairs, () => {}, edits);
  Object.defineProperty(output, "name", {value: "repaired.ifc"});
  verifyRepairedModel(await loadIfc(output), repairs);
  await verifyNoDanglingReferences(output, repairs);
  assert.match(await output.text(), /#213=IFCPRESENTATIONLAYERASSIGNMENT\('A-WALL',\/\* note, \(x \*\/\$,\(#203\),\$\);/);
});

test("\\X4\\ supplementary characters are decoded", () => {
  assert.equal(decodeStepText("Room \\X4\\0001F6AA0002000B\\X0\\"), "Room \u{1F6AA}\u{2000B}");
  assert.equal(decodeStepText("\\X2\\00E9\\X0\\"), "é");
});

test("an entity right after DATA; on the same line is read", async () => {
  const blob = new Blob([`ISO-10303-21;HEADER;FILE_DESCRIPTION(('Test'),'2;1');FILE_NAME('c.ifc','',(),(),'','','');FILE_SCHEMA(('IFC4'));ENDSEC;DATA;#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);#2=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);ENDSEC;END-ISO-10303-21;`]);
  Object.defineProperty(blob, "name", {value: "compact.ifc"});
  const model = await loadIfc(blob);
  assert.deepEqual([...model.entities.keys()], [1, 2]);
});

test("a comment before a missing context is skipped and the context is repaired", async () => {
  const fixture = await readFile(fileURLToPath(new URL("./fixtures/direct-missing-context.ifc", import.meta.url)), "latin1");
  const source = new Blob([fixture.replace("#300=IFCSHAPEREPRESENTATION($,", "#300=IFCSHAPEREPRESENTATION(/* no context, yet */ $,")]);
  Object.defineProperty(source, "name", {value: "commented.ifc"});
  const analysis = await analyzeIfc(await loadIfc(source));
  const issue = analysis.issues.find(item => item.id === 300);
  assert.equal(issue?.status, "Repairable");
  const {output, repairs, edits} = await applyRepairs(source, analysis.issues.filter(item => item.selected));
  await verifyRepairs(source, output, repairs, () => {}, edits);
  Object.defineProperty(output, "name", {value: "repaired.ifc"});
  verifyRepairedModel(await loadIfc(output), repairs);
  assert.match(await output.text(), /#300=IFCSHAPEREPRESENTATION\(\/\* no context, yet \*\/ #\d+,/);
});

test("comments around and inside an attribute do not stop an empty-shell repair", async () => {
  const source = ifcFile(`#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#20,$);
#11=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#10,$,.MODEL_VIEW.,$);
#20=IFCAXIS2PLACEMENT3D(#21,$,$);
#21=IFCCARTESIANPOINT((0.,0.,0.));
#30=IFCPROJECT('0PROJECT00000000000000',$,'Test',$,$,$,$,(#10),$);
#40=IFCLOCALPLACEMENT($,#20);
#100=IFCCLOSEDSHELL(());
#101=IFCFACETEDBREP(#100);
#110=IFCSHAPEREPRESENTATION(#11,'Body','Brep',(#101));
#111=IFCPRODUCTDEFINITIONSHAPE($,$,(#110));
#112=IFCSHADINGDEVICE('3ZEdFlJ3p0Wgv8suCk$gCR',$,'Louver',$,'Louver',#40, /* shape */ #111 /* end */,'985751',.USERDEFINED.);
#120=IFCCLOSEDSHELL(());
#121=IFCFACETEDBREP(#120);
#122=IFCPOLYLOOP((#21,#21,#21));
#123=IFCFACEOUTERBOUND(#122,.T.);
#124=IFCFACE((#123));
#125=IFCCLOSEDSHELL((#124));
#126=IFCFACETEDBREP(#125);
#130=IFCSHAPEREPRESENTATION(#11,'Body','Brep',(#121,#126));
#131=IFCPRODUCTDEFINITIONSHAPE($,$,(#130));
#132=IFCCOVERING('12DQx$oWulOrJZ_ULZbCcw',$,'Panel',$,'SANDWICHPANEL',#40,#131,'1076467',.CLADDING.);
#133=IFCPRESENTATIONLAYERASSIGNMENT('A-WALL',$,/* items */ (#121, /* empty */ #126),$);`);
  const analysis = await analyzeIfc(await loadIfc(source));
  assert.ok(analysis.issues.length && analysis.issues.every(issue => issue.status === "Repairable"));
  const {output, repairs, edits} = await applyRepairs(source, analysis.issues.filter(issue => issue.selected));
  await verifyRepairs(source, output, repairs, () => {}, edits);
  Object.defineProperty(output, "name", {value: "repaired.ifc"});
  verifyRepairedModel(await loadIfc(output), repairs);
  await verifyNoDanglingReferences(output, repairs);
  const text = await output.text();
  assert.match(text, /#112=IFCSHADINGDEVICE\([^;]*#40, \/\* shape \*\/ \$ \/\* end \*\/,'985751'/);
  assert.match(text, /#133=IFCPRESENTATIONLAYERASSIGNMENT\('A-WALL',\$,\/\* items \*\/ \(#126\),\$\);/);
});
