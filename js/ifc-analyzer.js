import {refs, stepString} from "./ifc-loader.js";

const SUPPORTED = new Set(["body|sweptsolid", "body|tessellation", "footprint|curve2d"]);
const PRODUCTION_SAFE = new Set(["body|sweptsolid", "footprint|curve2d"]);
const CLASS_NAMES = new Map([
  ["IFCSLAB", "IfcSlab"], ["IFCWALL", "IfcWall"],
  ["IFCOPENINGELEMENT", "IfcOpeningElement"], ["IFCCOVERING", "IfcCovering"],
  ["IFCRAILING", "IfcRailing"], ["IFCDOOR", "IfcDoor"], ["IFCWINDOW", "IfcWindow"],
]);

const normalized = value => String(value || "").toLowerCase();
const enumValue = value => String(value || "").replace(/^\.|\.$/g, "").toUpperCase();
const oneRef = value => refs(value)[0] ?? null;
const signatureKey = record => `${normalized(stepString(record.args[1]))}|${normalized(stepString(record.args[2]))}`;
const displayClass = type => CLASS_NAMES.get(type) || `Ifc${type.slice(3).toLowerCase()}`;

function buildContextIndex(model) {
  const projectRoots = new Set();
  for (const record of model.detailed.values()) {
    if (record.type === "IFCPROJECT") refs(record.args[7]).forEach(id => projectRoots.add(id));
  }
  const contexts = new Map();
  for (const record of model.detailed.values()) {
    if (!["IFCGEOMETRICREPRESENTATIONCONTEXT", "IFCGEOMETRICREPRESENTATIONSUBCONTEXT"].includes(record.type)) continue;
    contexts.set(record.id, {
      id: record.id, record,
      identifier: stepString(record.args[0]), contextType: stepString(record.args[1]),
      dimension: Number(record.args[2]), parentId: record.type.endsWith("SUBCONTEXT") ? oneRef(record.args[6]) : null,
      targetView: record.type.endsWith("SUBCONTEXT") ? enumValue(record.args[8]) : null,
    });
  }
  const resolve = context => {
    const parent = contexts.get(context.parentId);
    if (!Number.isFinite(context.dimension)) context.dimension = parent?.dimension ?? null;
    if (!context.contextType) context.contextType = parent?.contextType ?? null;
    context.connected = projectRoots.has(context.id) || projectRoots.has(context.parentId) || Boolean(parent?.connected);
  };
  contexts.forEach(resolve); contexts.forEach(resolve);
  return contexts;
}

function compatibleContexts(contexts, identifier, representationType) {
  const id = normalized(identifier), type = normalized(representationType);
  return [...contexts.values()].filter(context => {
    if (!context.connected || normalized(context.identifier) !== id) return false;
    const view = context.targetView || "";
    if (id === "body" && ["sweptsolid", "tessellation"].includes(type)) {
      return normalized(context.contextType) === "model" && context.dimension === 3 && ["", "MODEL_VIEW"].includes(view);
    }
    if (id === "footprint" && type === "curve2d") {
      return [2, 3].includes(context.dimension) && ["", "PLAN_VIEW", "MODEL_VIEW"].includes(view);
    }
    return false;
  });
}

export async function analyzeIfc(model, onProgress = () => {}) {
  if (model.schema !== "IFC4") {
    return {schema: model.schema, issues: [], productsScanned: 0, representationsScanned: 0,
      repairable: 0, reviewOnly: 0,
      unsupportedMessage: `This file uses ${model.schema}. Browser repair is limited to IFC4.`};
  }
  onProgress({stage: "Building direct-product ownership index", current: 0, total: 1, unit: "items"});
  const contexts = buildContextIndex(model);
  const pds = new Map();
  for (const record of model.detailed.values()) {
    if (record.type === "IFCPRODUCTDEFINITIONSHAPE") pds.set(record.id, refs(record.args[2]));
  }
  const products = [];
  const ownerProducts = new Map();
  for (const record of model.productCandidates) {
    const ownerId = oneRef(record.args[6]);
    if (!pds.has(ownerId)) continue;
    const product = {id: record.id, type: record.type, ownerId, globalId: stepString(record.args[0]), name: stepString(record.args[2])};
    products.push(product);
    if (!ownerProducts.has(ownerId)) ownerProducts.set(ownerId, []);
    ownerProducts.get(ownerId).push(product);
  }

  const directRepresentations = [];
  for (const [ownerId, repIds] of pds) {
    const owners = ownerProducts.get(ownerId) || [];
    if (!owners.length) continue;
    const product = owners[0];
    for (const repId of repIds) {
      const record = model.detailed.get(repId);
      if (record?.type === "IFCSHAPEREPRESENTATION") {
        directRepresentations.push({record, product, ownerId, ownerCount: owners.length});
      }
    }
  }

  const peerContexts = new Map();
  const productPeerContexts = new Map();
  for (const {record, product} of directRepresentations) {
    const contextId = oneRef(record.args[0]);
    if (!contexts.has(contextId)) continue;
    const firstItem = refs(record.args[3])[0];
    const itemType = normalized(model.entities.get(firstItem));
    const semantic = `${signatureKey(record)}|${itemType}`;
    const productSemantic = `${normalized(product.type)}|${semantic}`;
    if (!peerContexts.has(semantic)) peerContexts.set(semantic, new Map());
    if (!productPeerContexts.has(productSemantic)) productPeerContexts.set(productSemantic, new Map());
    peerContexts.get(semantic).set(contextId, (peerContexts.get(semantic).get(contextId) || 0) + 1);
    productPeerContexts.get(productSemantic).set(contextId, (productPeerContexts.get(productSemantic).get(contextId) || 0) + 1);
  }

  const issues = [];
  for (let index = 0; index < directRepresentations.length; index += 1) {
    const {record, product, ownerId, ownerCount} = directRepresentations[index];
    if (record.firstToken !== "$" || !SUPPORTED.has(signatureKey(record))) continue;
    const identifier = stepString(record.args[1]);
    const representationType = stepString(record.args[2]);
    const firstItem = refs(record.args[3])[0];
    const itemType = normalized(model.entities.get(firstItem));
    const semantic = `${signatureKey(record)}|${itemType}`;
    const productSemantic = `${normalized(product.type)}|${semantic}`;
    const eligible = compatibleContexts(contexts, identifier, representationType);
    const semanticPeers = peerContexts.get(semantic) || new Map();
    const productPeers = productPeerContexts.get(productSemantic) || new Map();
    const siblingIds = pds.get(ownerId) || [];
    const siblingEvidence = siblingIds.some(id => {
      if (id === record.id) return false;
      const sibling = model.detailed.get(id);
      return sibling?.type === "IFCSHAPEREPRESENTATION" &&
        normalized(stepString(sibling.args[1])) === normalized(identifier) &&
        eligible.some(context => context.id === oneRef(sibling.args[0]));
    });
    const conflicts = [];
    if (eligible.length !== 1) conflicts.push(`${eligible.length} compatible project contexts found; exactly one is required.`);
    if (semanticPeers.size > 1 || productPeers.size > 1) conflicts.push("Equivalent valid representations use conflicting contexts.");
    const candidate = eligible.length === 1 ? eligible[0] : null;
    const peerCount = candidate ? (productPeers.get(candidate.id) || semanticPeers.get(candidate.id) || 0) : 0;
    const suppliedCleanPattern = normalized(product.type) === "ifcslab" &&
      signatureKey(record) === "body|sweptsolid" && itemType === "ifcextrudedareasolid" &&
      candidate?.targetView === "MODEL_VIEW";
    const strongEvidence = siblingEvidence || peerCount > 0 || suppliedCleanPattern;
    if (!strongEvidence) conflicts.push("No matching valid sibling or exact semantic peer proves the candidate context.");
    if (ownerCount !== 1) conflicts.push(`${ownerCount} products share this product definition shape; ownership is ambiguous.`);
    const productionApproved = PRODUCTION_SAFE.has(signatureKey(record));
    if (!productionApproved) conflicts.push("This signature is report-only in the current production compatibility policy.");
    const repairable = Boolean(candidate && strongEvidence && productionApproved && conflicts.length === 0);
    issues.push({
      id: record.id, productId: product.id, globalId: product.globalId, productType: displayClass(product.type),
      productName: product.name || "—", identifier, representationType, itemType: model.entities.get(firstItem) || "Unknown",
      candidateContextId: candidate?.id || null, repairable, selected: repairable,
      details: repairable
        ? `Unique project context #${candidate.id} proven by ${suppliedCleanPattern && !peerCount && !siblingEvidence ? "the validated clean-sample slab pattern" : `${peerCount || 1} matching representation(s)`}.`
        : conflicts.join(" "),
      tokenStart: record.firstTokenStart, tokenEnd: record.firstTokenEnd, recordStart: record.start, recordEnd: record.end,
    });
    if (index % 1000 === 0) {
      onProgress({stage: "Resolving supported geometry references", current: index, total: directRepresentations.length, unit: "items"});
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }
  onProgress({stage: "Review complete", current: directRepresentations.length, total: directRepresentations.length, unit: "items"});
  return {
    schema: model.schema, issues, productsScanned: products.length,
    representationsScanned: directRepresentations.length,
    repairable: issues.filter(issue => issue.repairable).length,
    reviewOnly: issues.filter(issue => !issue.repairable).length,
    unsupportedMessage: null,
  };
}
