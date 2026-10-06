import {storedZip} from "./zip-exporter.js?v=2.1";

const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const encoder = new TextEncoder();

const ACTIONS = {
  shapeFailed: "Open a plan view and a 3D view with the room or area interior visible. Look for very short or overlapping boundary lines, thin slivers or narrow gaps, and simplify the boundary or its separation lines. Export the IFC again and check the new file here.",
  noArea: "Close the boundary with walls, room separation lines or area boundary lines, or delete the room or area if it is redundant or not needed. Export the IFC again and check the new file here.",
  noHeight: "Set the Upper Limit and Limit Offset so the top of the room is above its base. Export the IFC again and check the new file here.",
  noData: "Check the room or area in plan and in 3D. Turn on Export base quantities in the IFC export setup so the next check can show the cause.",
};

export function areaAction(space) {
  const find = space.revitId === "Not Found"
    ? "Find it by Number and Name in the Room or Area schedule."
    : "Find it with Manage > Select by ID and the Revit Lookup ID.";
  return `${find} ${ACTIONS[space.reason] || ACTIONS.noData}`;
}

const SHEETS = [
  {
    name: "Areas without geometry",
    columns: [["No.", 6], ["File", 34], ["Level", 18], ["Number", 14], ["Name", 28], ["Object Type", 14], ["Revit Lookup ID", 16],
      ["Area", 14], ["Height", 12], ["Why no geometry", 34], ["Explanation", 70], ["What to do in Revit", 80], ["GUID", 26], ["PredefinedType", 16]],
    rows: analysis => analysis.spaceIssues.map((space, index) => [
      index + 1, space.fileName, space.level, space.number, space.name, space.objectType, space.revitId,
      space.area, space.height, space.reasonLabel, space.reasonDetail, areaAction(space), space.guid, space.predefinedType,
    ]),
  },
  {
    name: "How to use",
    columns: [["Areas without geometry report", 120]],
    rows: () => [
      ["Each row is an IfcSpace (a Revit room, space or area) that was exported with no shape (IfcSpace.Representation = $)."],
      ["The repair tool cannot add a shape: the IFC file has no correct outline for these spaces. They stay unchanged in the repaired IFC."],
      ["Fix each one in Revit, then export the IFC again and check the new file with the tool."],
      ["Why no geometry is read from the area and height that Revit exported for the space (Qto_SpaceBaseQuantities)."],
      ["Has area, but Revit could not build the 3D shape: the room is placed and enclosed, but its boundary could not be turned into a 3D shape."],
      ["Area is 0: the room or area is not enclosed, or it is redundant."],
      ["Has area but height is 0: the upper limit or limit offset puts the top of the room at or below its base."],
      ["No area data in the IFC: base quantities were not exported, so the cause cannot be read from the file."],
    ],
  },
];

// Drops characters XML 1.0 does not allow, then escapes markup.
function xmlText(value) {
  return String(value ?? "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g, "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const columnLetter = index => String.fromCharCode(65 + index);

function worksheetXml(sheet, analysis) {
  const rows = [sheet.columns.map(([title]) => title), ...sheet.rows(analysis)];
  const last = `${columnLetter(sheet.columns.length - 1)}${rows.length}`;
  const rowXml = rows.map((row, rowIndex) => `<row r="${rowIndex + 1}">${row.map((value, columnIndex) => {
    const ref = `${columnLetter(columnIndex)}${rowIndex + 1}`;
    if (typeof value === "number") return `<c r="${ref}"${rowIndex ? "" : ' s="1"'}><v>${value}</v></c>`;
    return `<c r="${ref}" t="inlineStr" s="${rowIndex ? 2 : 1}"><is><t xml:space="preserve">${xmlText(value)}</t></is></c>`;
  }).join("")}</row>`).join("");
  const cols = sheet.columns.map(([, width], index) => `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:${last}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>${cols}</cols><sheetData>${rowXml}</sheetData><autoFilter ref="A1:${last}"/></worksheet>`;
}

function workbookParts(analysis) {
  const sheetIds = SHEETS.map((_, index) => index + 1);
  return {
    "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>${sheetIds.map(id => `<Override PartName="/xl/worksheets/sheet${id}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("")}<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`,
    "_rels/.rels": `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
    "xl/workbook.xml": `<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>${SHEETS.map((sheet, index) => `<sheet name="${sheet.name}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`).join("")}</sheets></workbook>`,
    "xl/_rels/workbook.xml.rels": `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheetIds.map(id => `<Relationship Id="rId${id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${id}.xml"/>`).join("")}<Relationship Id="rId${SHEETS.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`,
    // Style 1: bold header. Style 2: text that wraps, so long Revit IDs and GUIDs never turn into numbers.
    "xl/styles.xml": `<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`,
    ...Object.fromEntries(SHEETS.map((sheet, index) => [`xl/worksheets/sheet${index + 1}.xml`, worksheetXml(sheet, analysis)])),
  };
}

export async function buildAreaReport(analysis) {
  const entries = Object.entries(workbookParts(analysis)).map(([name, xml]) => ({name, blob: new Blob([encoder.encode(xml)])}));
  return storedZip(entries, () => {}, XLSX_TYPE);
}

export function areaReportName(analysis) {
  if (analysis.files.length !== 1) return "IFC-SG_Areas_without_geometry.xlsx";
  const stem = analysis.files[0].fileName.replace(/\.ifc$/i, "").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_");
  return `${stem}_Areas_without_geometry.xlsx`;
}
