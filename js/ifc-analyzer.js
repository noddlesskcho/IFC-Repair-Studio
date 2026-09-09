import {refs, stepString} from "./ifc-loader.js?v=1.0.0-r6";

const SUPPORTED = new Set(["body|sweptsolid", "body|tessellation", "footprint|curve2d"]);
const REFERENCE_LABELS = new Map([
  ["IFCPRODUCTDEFINITIONSHAPE", "IfcProductDefinitionShape"],
  ["IFCSHAPEASPECT", "IfcShapeAspect"],
  ["IFCPRESENTATIONLAYERASSIGNMENT", "IfcPresentationLayerAssignment"],
  ["IFCPRESENTATIONLAYERWITHSTYLE", "IfcPresentationLayerWithStyle"],
  ["IFCREPRESENTATIONMAP", "IfcRepresentationMap"],
]);
const CLASS_NAMES = new Map([
  ["IFCSLAB", "IfcSlab"], ["IFCWALL", "IfcWall"],
  ["IFCOPENINGELEMENT", "IfcOpeningElement"], ["IFCCOVERING", "IfcCovering"],
  ["IFCRAILING", "IfcRailing"], ["IFCDOOR", "IfcDoor"], ["IFCWINDOW", "IfcWindow"],
]);

const normalized = value => String(value || "").toLowerCase();
const enumValue = value => String(value || "").replace(/^\.|\.$/g, "").toUpperCase();
const oneRef = value => refs(value)[0] ?? null;
const signatureKey = record => `${normalized(stepString(record.args[1]))}|${normalized(stepString(record.args[2]))}`;
const displayClass = type => CLASS_NAMES.get(type) || (type?.startsWith("IFC") ? `Ifc${type.slice(3).toLowerCase()}` : "Unknown");

function buildContextIndex(model) {
  const projectRoots = new Set();
  for (const record of model.detailed.values()) {
    if (record.type === "IFCPROJECT") refs(record.args[7]).forEach(id => projectRoots.add(id));
  }
  const contexts = new Map();
  for (const record of model.detailed.values()) {
    if (!["IFCGEOMETRICREPRESENTATIONCONTEXT", "IFCGEOMETRICREPRESENTATIONSUBCONTEXT"].includes(record.type)) continue;
    contexts.set(record.id, {
      id: record.id,
      entityType: record.type,
      identifier: stepString(record.args[0]),
      contextType: stepString(record.args[1]),
      dimension: Number(record.args[2]),
      parentId: record.type === "IFCGEOMETRICREPRESENTATIONSUBCONTEXT" ? oneRef(record.args[6]) : null,
      targetView: record.type === "IFCGEOMETRICREPRESENTATIONSUBCONTEXT" ? enumValue(record.args[8]) : null,
      connected: false,
    });
  }

  const connected = (context, visiting = new Set()) => {
    if (projectRoots.has(context.id)) return true;
    if (!context.parentId || visiting.has(context.id)) return false;
    const parent = contexts.get(context.parentId);
    if (!parent) return false;
    visiting.add(context.id);
    return connected(parent, visiting);
  };
  for (const context of contexts.values()) {
    const parent = contexts.get(context.parentId);
    if (!Number.isFinite(context.dimension)) context.dimension = parent?.dimension ?? null;
    if (!context.contextType) context.contextType = parent?.contextType ?? null;
    context.connected = connected(context);
  }
  return contexts;
}

function compatibleContexts(contexts, identifier, representationType) {
  const id = normalized(identifier);
  const type = normalized(representationType);
  return [...contexts.values()].filter(context => {
    if (!context.connected || normalized(context.identifier) !== id) return false;
    if (id === "body" && ["sweptsolid", "tessellation"].includes(type)) {
      return normalized(context.contextType) === "model" && context.dimension === 3 &&
        (context.entityType === "IFCGEOMETRICREPRESENTATIONCONTEXT" || context.targetView === "MODEL_VIEW");
    }
    if (id === "footprint" && type === "curve2d") {
      return [2, 3].includes(context.dimension) &&
        (context.entityType === "IFCGEOMETRICREPRESENTATIONCONTEXT" || ["PLAN_VIEW", "MODEL_VIEW"].includes(context.targetView));
    }
    return false;
  });

}

function buildReferenceIndex(model) {
  const index = new Map();
  const add = (targetId, source) => {
    if (!index.has(targetId)) index.set(targetId, []);
    index.get(targetId).push(source);
  };
  for (const record of model.detailed.values()) {
    let targetIds = [];
    if (record.type === "IFCPRODUCTDEFINITIONSHAPE") targetIds = refs(record.args[2]);
    else if (record.type === "IFCSHAPEASPECT") targetIds = refs(record.args[0]);
    else if (["IFCPRESENTATIONLAYERASSIGNMENT", "IFCPRESENTATIONLAYERWITHSTYLE"].includes(record.type)) targetIds = refs(record.args[2]);
    else if (record.type === "IFCREPRESENTATIONMAP") targetIds = refs(record.args[1]);
    else continue;
    for (const targetId of targetIds) {
      if (model.entities.get(targetId) === "IFCSHAPEREPRESENTATION") {
        add(targetId, {id: record.id, type: record.type, label: REFERENCE_LABELS.get(record.type)});
      }
    }
  }
  return index;
}

function buildProductIndex(model) {
  const byDefinition = new Map();
  for (const record of model.productCandidates) {
    const definitionId = oneRef(record.args[6]);
    if (!definitionId) continue;
    if (!byDefinition.has(definitionId)) byDefinition.set(definitionId, []);
    byDefinition.get(definitionId).push({
      id: record.id,
      type: record.type,
      globalId: stepString(record.args[0]),
      name: stepString(record.args[2]),
    });
  }
  return byDefinition;
}

function productForRepresentation(referenceSources, model, productsByDefinition) {
  for (const source of referenceSources) {
    if (source.type === "IFCPRODUCTDEFINITIONSHAPE") {
      const product = productsByDefinition.get(source.id)?.[0];
      if (product) return product;
    }
    if (source.type === "IFCSHAPEASPECT") {
      const aspect = model.detailed.get(source.id);
      const definitionId = oneRef(aspect?.args[4]);
      const product = productsByDefinition.get(definitionId)?.[0];
      if (product) return product;
    }
  }
  return null;
}

function summaryCounts(issues) {
  const bySignature = {bodySweptSolid: 0, bodyTessellation: 0, footprintCurve2D: 0};
  for (const issue of issues) {
    if (issue.signature === "body|sweptsolid") bySignature.bodySweptSolid += 1;
    else if (issue.signature === "body|tessellation") bySignature.bodyTessellation += 1;
    else if (issue.signature === "footprint|curve2d") bySignature.footprintCurve2D += 1;
  }
  return bySignature;
}

export async function analyzeIfc(model, onProgress = () => {}) {
  if (model.schema !== "IFC4") {
    return {schema: model.schema, issues: [], productsScanned: 0, representationsScanned: 0,
      repairable: 0, reviewOnly: 0, counts: summaryCounts([]),
      unsupportedMessage: `This file uses ${model.schema}. Browser repair is limited to IFC4.`};
  }

  onProgress({stage: "Indexing representation contexts and references", current: 0, total: 1, unit: "items"});
  const contexts = buildContextIndex(model);
  const referenceIndex = buildReferenceIndex(model);
  const productsByDefinition = buildProductIndex(model);
  const representations = [...model.detailed.values()].filter(record => record.type === "IFCSHAPEREPRESENTATION");
  const issues = [];

  for (let index = 0; index < representations.length; index += 1) {
    const record = representations[index];
    const signature = signatureKey(record);
    if (record.firstToken !== "$" || !SUPPORTED.has(signature)) continue;
    const identifier = stepString(record.args[1]);
    const representationType = stepString(record.args[2]);
    const eligible = compatibleContexts(contexts, identifier, representationType);
    const candidate = eligible.length === 1 ? eligible[0] : null;
    const referenceSources = referenceIndex.get(record.id) || [];
    const referenceTypes = [...new Set(referenceSources.map(source => source.label))];
    const product = productForRepresentation(referenceSources, model, productsByDefinition);
    const firstItem = refs(record.args[3])[0];
    const repairable = Boolean(candidate);
    const status = repairable ? "Repairable" : eligible.length ? "Review Required" : "No Compatible Context";
    const reason = repairable
      ? `Exactly one compatible project-connected context was found: #${candidate.id} ${candidate.identifier} / ${candidate.contextType}.`
      : eligible.length
        ? `${eligible.length} compatible project-connected contexts were found (${eligible.map(context => `#${context.id}`).join(", ")}); automatic repair requires exactly one.`
        : `No compatible project-connected ${identifier} context was found.`;
    issues.push({
      id: record.id,
      signature,
      productId: product?.id || null,
      globalId: product?.globalId || null,
      productType: product ? displayClass(product.type) : referenceTypes[0] || "Unresolved reference",
      productName: product?.name || "—",
      identifier,
      representationType,
      itemType: model.entities.get(firstItem) || "Unknown",
      currentContext: "Missing ($)",
      candidateContextId: candidate?.id || null,
      candidateContextType: candidate?.entityType || null,
      proposedContext: candidate ? `#${candidate.id} ${candidate.identifier} / ${candidate.contextType}` : "—",
      referencedBy: referenceTypes.length ? referenceTypes : ["Unindexed representation reference"],
      repairable,
      status,
      selected: repairable,
      reason,
      details: reason,
      tokenStart: record.firstTokenStart,
      tokenEnd: record.firstTokenEnd,
      recordStart: record.start,
      recordEnd: record.end,
    });
    if (index % 1000 === 0) {
      onProgress({stage: "Checking all shape representations", current: index, total: representations.length, unit: "items"});
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }
  onProgress({stage: "Review complete", current: representations.length, total: representations.length, unit: "items"});
  return {
    schema: model.schema,
    issues,
    productsScanned: model.productCandidates.length,
    representationsScanned: representations.length,
    repairable: issues.filter(issue => issue.repairable).length,
    reviewOnly: issues.filter(issue => !issue.repairable).length,
    counts: summaryCounts(issues),
    unsupportedMessage: null,
  };
}
