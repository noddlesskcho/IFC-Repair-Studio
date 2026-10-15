import assert from "node:assert/strict";
import test from "node:test";

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
