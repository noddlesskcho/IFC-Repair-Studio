import {refs, stepString} from "./ifc-loader.js?v=2.1";

// Spatial containers a space can sit in on its way up to a storey.
const SPATIAL_PARENTS = new Set(["IFCSPACE", "IFCBUILDINGSTOREY", "IFCBUILDING", "IFCSITE", "IFCSPATIALZONE", "IFCPROJECT"]);

// IFC strings encode non-ASCII text as \X2\hhhh\X0\ (UTF-16) or \X\hh (ISO 8859-1).
export function decodeStepText(text) {
  return String(text)
    .replace(/\\X2\\((?:[0-9A-F]{4})+)\\X0\\/gi, (_, hex) => String.fromCharCode(...hex.match(/.{4}/g).map(code => parseInt(code, 16))))
    .replace(/\\X\\([0-9A-F]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
}

const display = value => {
  const text = stepString(value);
  if (text === null || text === undefined || String(text).trim() === "") return "N/A";
  return decodeStepText(String(text).replace(/^\./, "").replace(/\.$/, "")) || "N/A";
};

const firstDisplay = (...values) => values.map(display).find(text => text !== "N/A") || "N/A";

const storeyName = storey => firstDisplay(storey.name, storey.longName, storey.objectType);

function parentIndex(pairs) {
  const parents = new Map();
  for (const [parentId, childIds] of pairs) for (const childId of childIds) parents.set(childId, parentId);
  return parents;
}

function resolveLevel(space, model, aggregateParent, containmentParent) {
  const storeys = model.spatial.storeys;
  const level = (storey, method) => ({level: storeyName(storey), levelGuid: display(storey.globalId), levelMethod: method});
  const directAggregate = storeys.get(aggregateParent.get(space.id));
  if (directAggregate) return level(directAggregate, "IfcRelAggregates");
  const directContainer = storeys.get(containmentParent.get(space.id));
  if (directContainer) return level(directContainer, "IfcRelContainedInSpatialStructure");
  const visited = new Set();
  const stack = [space.id];
  while (stack.length) {
    const currentId = stack.pop();
    if (!currentId || visited.has(currentId)) continue;
    visited.add(currentId);
    for (const parentId of [aggregateParent.get(currentId), containmentParent.get(currentId)]) {
      if (!parentId) continue;
      if (storeys.has(parentId)) return level(storeys.get(parentId), "HierarchyTraversal");
      if (SPATIAL_PARENTS.has(model.entities.get(parentId))) stack.push(parentId);
    }
  }
  return {level: "N/A", levelGuid: "N/A", levelMethod: "N/A"};
}

// Revit exports one IfcSpaceType per room or area and writes the Revit element ID as its Tag.
function resolveRevitId(space, model, typesBySpace) {
  for (const typeId of typesBySpace.get(space.id) || []) {
    if (!model.spatial.spaceTypeTags.has(typeId)) continue;
    const tag = display(model.spatial.spaceTypeTags.get(typeId));
    if (/^\d+$/.test(tag)) return {revitId: tag, revitIdStatus: "Valid"};
    if (tag !== "N/A") return {revitId: "Not Found", revitIdStatus: `Non-numeric IfcSpaceType.Tag: ${tag}`};
  }
  return {revitId: "Not Found", revitIdStatus: "Not Found"};
}

const SI_PREFIXES = {MILLI: "m", CENTI: "c", DECI: "d", KILO: "k"};
const unitLabel = (unit, power) => unit?.name?.endsWith("METRE") ? `${SI_PREFIXES[unit.prefix] || ""}m${power}` : "";
// Units come from IfcProject.UnitsInContext; a file can hold other IfcSIUnit records that the project does not use.
function projectUnits(model) {
  const project = [...model.detailed.values()].find(record => record.type === "IFCPROJECT");
  const assigned = model.spatial.unitAssignments.get(refs(project?.args[8] || "")[0]) || [];
  const units = assigned.map(id => model.spatial.units.get(id)).filter(Boolean);
  const ofType = type => units.find(unit => unit.type === type);
  return {area: unitLabel(ofType("AREAUNIT"), "²"), length: unitLabel(ofType("LENGTHUNIT"), "")};
}

const formatNumber = (value, digits) => value.toLocaleString("en-US", {minimumFractionDigits: digits, maximumFractionDigits: digits});

// Explains the missing shape from Revit's exported base quantities (Qto_SpaceBaseQuantities).
// Revit writes the room's calculated area and height even when it cannot build the 3D shape.
export function whyNoGeometry(area, height) {
  if (area === null) {
    return {reason: "noData", reasonLabel: "No area data in the IFC",
      reasonDetail: "The IFC has no base quantities for this space (Export base quantities may be off), so the cause cannot be read from the file."};
  }
  if (area <= 0) {
    return {reason: "noArea", reasonLabel: "Area is 0: not enclosed or redundant",
      reasonDetail: "Revit calculated no floor area. The room or area is not enclosed by its boundaries, or it is redundant (two rooms in one enclosed region)."};
  }
  if (height !== null && height <= 0) {
    return {reason: "noHeight", reasonLabel: "Has area but height is 0",
      reasonDetail: "Revit calculated a floor area but no height. The upper limit or limit offset puts the top of the room at or below its base."};
  }
  return {reason: "shapeFailed", reasonLabel: "Has area, but Revit could not build the 3D shape",
    reasonDetail: "Revit calculated the area and height, so the room is placed and enclosed, but its IFC export could not turn the room boundary into a 3D shape. Common causes are very short or overlapping boundary lines, thin slivers or narrow gaps in the boundary, or a boundary that changes over the room height."};
}

// Finds every IfcSpace whose Representation is missing ($). These cannot be repaired in the IFC:
// the room or area has no shape to export, so it must be fixed in Revit.
export async function analyzeSpaces(model, onProgress = () => {}) {
  const spaces = model.spatial?.spaces || [];
  const missing = spaces.filter(space => !space.representation || space.representation === "$");
  if (!missing.length) return {spaceCount: spaces.length, issues: []};

  onProgress({stage: "Checking IfcSpace geometry", current: 0, total: missing.length, unit: "items"});
  const aggregateParent = parentIndex(model.spatial.aggregates);
  const containmentParent = parentIndex(model.spatial.containment);
  const typesBySpace = new Map();
  for (const [typeId, childIds] of model.spatial.typeLinks) {
    for (const childId of childIds) {
      if (!typesBySpace.has(childId)) typesBySpace.set(childId, []);
      typesBySpace.get(childId).push(typeId);
    }
  }

  const quantitiesBySpace = new Map();
  for (const [setId, spaceIds] of model.spatial.quantityLinks) {
    const values = {};
    for (const quantityId of model.spatial.spaceQuantitySets.get(setId) || []) {
      const quantity = model.spatial.quantities.get(quantityId);
      if (quantity && Number.isFinite(quantity.value)) values[quantity.name] = quantity.value;
    }
    for (const spaceId of spaceIds) quantitiesBySpace.set(spaceId, {...quantitiesBySpace.get(spaceId), ...values});
  }
  const units = projectUnits(model);

  const issues = missing.map(space => {
    const quantities = quantitiesBySpace.get(space.id) || {};
    const area = quantities.NetFloorArea ?? quantities.GrossFloorArea ?? null;
    const height = quantities.Height ?? null;
    return {
      stepId: space.id,
      number: display(space.name),
      name: firstDisplay(space.longName, space.description),
      ...resolveLevel(space, model, aggregateParent, containmentParent),
      predefinedType: display(space.predefinedType),
      objectType: display(space.objectType),
      guid: display(space.globalId),
      ...resolveRevitId(space, model, typesBySpace),
      area: area === null ? "N/A" : `${formatNumber(area, 2)} ${units.area}`,
      height: height === null ? "N/A" : `${formatNumber(height, units.length === "mm" ? 0 : 2)} ${units.length}`,
      boundaries: model.spatial.boundaryCounts.get(space.id) || 0,
      ...whyNoGeometry(area, height),
    };
  });
  const sortKey = issue => [issue.level, issue.number, issue.name, issue.objectType, issue.guid].join("|");
  issues.sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  onProgress({stage: "Checking IfcSpace geometry", current: missing.length, total: missing.length, unit: "items"});
  return {spaceCount: spaces.length, issues};
}
