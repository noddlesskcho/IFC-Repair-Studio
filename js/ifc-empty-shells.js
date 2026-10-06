import {codeRefs, scanReferences, stepString} from "./ifc-loader.js?v=2.1";

// IfcClosedShell.CfsFaces is SET [1:?] OF IfcFace, so IFCCLOSEDSHELL(()) is invalid IFC4.
// The repair removes each empty shell, the IfcFacetedBrep that wraps it, and every reference
// to that brep. A representation, product shape or layer assignment left with an empty list
// (also SET/LIST [1:?]) is removed as well, and a product left without a shape gets
// Representation = $ (the attribute is OPTIONAL). Anything outside that pattern is review-only.

const LAYER_TYPES = new Set(["IFCPRESENTATIONLAYERASSIGNMENT", "IFCPRESENTATIONLAYERWITHSTYLE"]);
const onlyArg = (user, index) => user.argIndexes.size === 1 && user.argIndexes.has(index);
const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

function unitFor(rep, emptyBreps) {
  const removed = rep.itemIds.filter(id => emptyBreps.has(id));
  return {
    rep, removed, kept: rep.itemIds.filter(id => !emptyBreps.has(id)),
    shells: removed.map(id => emptyBreps.get(id)), styledItems: new Set(), layers: new Map(),
    productShapes: new Map(), reasons: [],
  };
}

// Checks the parts of the chain that belong to one representation only.
function checkUnit(unit, users, contextIssueIds) {
  const {rep} = unit;
  if (rep.truncated) unit.reasons.push(`Representation #${rep.id} is too large to check safely.`);
  if (contextIssueIds.has(rep.id)) {
    unit.reasons.push(`Representation #${rep.id} also has a missing ContextOfItems. Repair the context first, then check the repaired IFC again.`);
  }
  if (new Set(rep.itemIds).size !== rep.itemIds.length) unit.reasons.push(`Representation #${rep.id} lists the same item twice.`);
  unit.removed.forEach((brepId, index) => {
    const shellId = unit.shells[index];
    const shellUsers = users.get(shellId) || [];
    if (shellUsers.length !== 1 || shellUsers[0].id !== brepId || !onlyArg(shellUsers[0], 0)) {
      unit.reasons.push(`Empty shell #${shellId} is used by more than its IfcFacetedBrep #${brepId}.`);
    }
    for (const user of users.get(brepId) || []) {
      if (user.type === "IFCSHAPEREPRESENTATION" && user.id === rep.id && onlyArg(user, 3)) continue;
      if (user.type === "IFCSTYLEDITEM" && onlyArg(user, 0)) { unit.styledItems.add(user.id); continue; }
      if (LAYER_TYPES.has(user.type) && onlyArg(user, 2)) { unit.layers.set(user.id, user); continue; }
      unit.reasons.push(`IfcFacetedBrep #${brepId} is also used by #${user.id} ${user.type}.`);
    }
  });
  if (!unit.kept.length) {
    for (const user of users.get(rep.id) || []) {
      if (user.type === "IFCPRODUCTDEFINITIONSHAPE" && onlyArg(user, 2)) { unit.productShapes.set(user.id, user); continue; }
      if (LAYER_TYPES.has(user.type) && onlyArg(user, 2)) { unit.layers.set(user.id, user); continue; }
      unit.reasons.push(`Representation #${rep.id} would become empty but is used by #${user.id} ${user.type}, which cannot lose it automatically.`);
    }
  }
}

function listRefs(user, index) {
  return codeRefs(user.args[index]);
}

// Merges the repairable units into one plan. Returns reasons per unit when a shared record blocks it.
function buildPlan(units, users, secondUsers) {
  const ops = new Map();
  const deleted = new Set();
  const blocked = new Map();
  const block = (unit, reason) => { if (!blocked.has(unit)) blocked.set(unit, []); blocked.get(unit).push(reason); };
  const add = op => ops.set(op.id, op);
  const record = (user, extra) => ({id: user.id, type: user.type, start: user.start, end: user.end, ...extra});

  for (const unit of units) {
    for (const [index, brepId] of unit.removed.entries()) {
      deleted.add(brepId); deleted.add(unit.shells[index]);
    }
    for (const id of unit.styledItems) {
      deleted.add(id);
      if ((secondUsers.get(id) || []).length) block(unit, `IfcStyledItem #${id} is referenced by another record.`);
    }
    if (!unit.kept.length) deleted.add(unit.rep.id);
  }

  // Product shapes and layers are shared records: remove all repairable references at once.
  const removeFrom = new Map();
  for (const unit of units) {
    for (const [id, user] of [...unit.productShapes, ...unit.layers]) {
      if (!removeFrom.has(id)) removeFrom.set(id, {user, units: new Set()});
      removeFrom.get(id).units.add(unit);
    }
  }
  const nulls = [];
  for (const [id, {user, units: owners}] of removeFrom) {
    const index = 2;
    if (user.truncated) { owners.forEach(unit => block(unit, `#${id} ${user.type} is too large to check safely.`)); continue; }
    const current = listRefs(user, index);
    const kept = current.filter(ref => !deleted.has(ref));
    const removeIds = current.filter(ref => deleted.has(ref));
    if (kept.length) {
      add(record(user, {kind: "removeRefs", argIndex: index, removeIds, keepCount: kept.length}));
      continue;
    }
    deleted.add(id);
    const holders = secondUsers.get(id) || users.get(id) || [];
    if (user.type === "IFCPRODUCTDEFINITIONSHAPE") {
      for (const holder of holders) {
        if (onlyArg(holder, 6) && !LAYER_TYPES.has(holder.type) && holder.args[6]?.trim() === `#${id}`) {
          nulls.push(record(holder, {kind: "setNull", argIndex: 6, expectedRef: id}));
        } else {
          owners.forEach(unit => block(unit, `IfcProductDefinitionShape #${id} would become empty but is used by #${holder.id} ${holder.type}.`));
        }
      }
    } else if (holders.length) {
      owners.forEach(unit => block(unit, `#${id} ${user.type} would become empty but is referenced by another record.`));
    }
  }

  for (const unit of units) {
    if (unit.kept.length) {
      const {rep} = unit;
      add({id: rep.id, type: rep.type, start: rep.start, end: rep.end, kind: "removeRefs", argIndex: 3, removeIds: unit.removed, keepCount: unit.kept.length});
    }
  }
  for (const op of nulls) add(op);
  return {ops, deleted, blocked};
}

export async function analyzeEmptyShells(model, {referenceIndex, productsByDefinition, contextIssueIds, productForRepresentation, displayClass}, onProgress = () => {}) {
  const shells = model.emptyShells || new Map();
  if (!shells.size) return [];

  const emptyBreps = new Map();
  for (const [brepId, shellId] of model.brepOuters || []) if (shells.has(shellId)) emptyBreps.set(brepId, shellId);
  const reps = [...model.detailed.values()].filter(record =>
    record.type === "IFCSHAPEREPRESENTATION" && record.itemIds?.some(id => emptyBreps.has(id)));
  const productShapeIds = new Set();
  for (const rep of reps) {
    for (const source of referenceIndex.get(rep.id) || []) if (source.type === "IFCPRODUCTDEFINITIONSHAPE") productShapeIds.add(source.id);
  }

  onProgress({stage: "Tracing empty IfcClosedShell references", current: 0, total: 1, unit: "items"});
  const users = await scanReferences(model.file, new Set([...shells.keys(), ...emptyBreps.keys(), ...reps.map(rep => rep.id), ...productShapeIds]), onProgress);

  let units = reps.map(rep => unitFor(rep, emptyBreps));
  units.forEach(unit => checkUnit(unit, users, contextIssueIds));

  // Records that may be deleted as a follow-up must themselves be unreferenced; scan for those once.
  const followUps = new Set();
  for (const unit of units) {
    unit.styledItems.forEach(id => followUps.add(id));
    unit.layers.forEach((_, id) => followUps.add(id));
  }
  const secondUsers = await scanReferences(model.file, followUps, onProgress);
  for (const id of productShapeIds) if (users.has(id)) secondUsers.set(id, users.get(id));

  let repairable = units.filter(unit => !unit.reasons.length);
  let plan = buildPlan(repairable, users, secondUsers);
  while (plan.blocked.size) {
    for (const [unit, reasons] of plan.blocked) unit.reasons.push(...reasons);
    repairable = units.filter(unit => !unit.reasons.length);
    plan = buildPlan(repairable, users, secondUsers);
  }

  const shared = repairable.length ? {
    ops: [...plan.ops.values(), ...[...plan.deleted].filter(id => !plan.ops.has(id)).map(id => deleteOp(id, model, users, shells))]
      .filter(Boolean).sort((a, b) => a.start - b.start),
    issueIds: repairable.map(unit => unit.rep.id),
    deletedIds: [...plan.deleted],
  } : null;
  if (shared && shared.ops.length < shared.deletedIds.length) throw new Error("Empty-shell repair plan is missing record positions.");

  const orphanShells = [...shells.keys()].filter(id => !units.some(unit => unit.shells.includes(id)));
  const issues = units.map(unit => issueFor(unit, model, referenceIndex, productsByDefinition, productForRepresentation, displayClass, shared));
  for (const shellId of orphanShells) {
    const shell = shells.get(shellId);
    issues.push({
      id: shellId, signature: "empty-closed-shell", issueType: "emptyClosedShell", productId: null, globalId: null,
      productType: "Unresolved reference", productName: "—", identifier: "—", representationType: "—", itemType: "IfcClosedShell",
      currentContext: "Empty IfcClosedShell", candidateContextId: null, proposedContext: "—",
      referencedBy: [(users.get(shellId) || []).map(user => user.type).join(", ") || "Not used by a shape representation"],
      repairable: false, status: "Review Required", selected: false,
      reason: `Empty IfcClosedShell #${shellId} is not reached through IfcFacetedBrep in an IfcShapeRepresentation.`,
      details: "", tokenStart: shell.start, tokenEnd: shell.start, recordStart: shell.start, recordEnd: shell.end,
    });
  }
  return issues;
}

function deleteOp(id, model, users, shells) {
  if (shells.has(id)) return {id, type: "IFCCLOSEDSHELL", start: shells.get(id).start, end: shells.get(id).end, kind: "delete"};
  const detailed = model.detailed.get(id);
  if (detailed) return {id, type: detailed.type, start: detailed.start, end: detailed.end, kind: "delete"};
  for (const list of users.values()) {
    const user = list.find(entry => entry.id === id);
    if (user) return {id, type: user.type, start: user.start, end: user.end, kind: "delete"};
  }
  return null;
}

function issueFor(unit, model, referenceIndex, productsByDefinition, productForRepresentation, displayClass, shared) {
  const {rep} = unit;
  const sources = referenceIndex.get(rep.id) || [];
  const product = productForRepresentation(sources, model, productsByDefinition);
  const repairable = !unit.reasons.length;
  const count = unit.removed.length;
  const proposed = unit.kept.length
    ? `Remove ${plural(count, "empty item")}; keep ${unit.kept.length}`
    : "Remove empty representation";
  const reason = repairable
    ? unit.kept.length
      ? `${plural(count, "IfcFacetedBrep")} with an empty IfcClosedShell will be removed. The other ${unit.kept.length} geometry item${unit.kept.length === 1 ? "" : "s"} stay.`
      : `All ${plural(count, "geometry item")} are empty IfcClosedShell solids. The representation is removed; the element stays${product ? " with Representation = $" : ""}.`
    : unit.reasons.join(" ");
  return {
    id: rep.id,
    signature: "empty-closed-shell",
    issueType: "emptyClosedShell",
    productId: product?.id || null,
    globalId: product?.globalId || null,
    productType: product ? displayClass(product.type) : "Unresolved reference",
    productName: product?.name || "—",
    identifier: stepString(rep.args[1]),
    representationType: stepString(rep.args[2]),
    itemType: "IfcFacetedBrep",
    currentContext: `${plural(count, "empty IfcClosedShell")} of ${rep.itemIds.length} items`,
    candidateContextId: null,
    proposedContext: proposed,
    referencedBy: [product ? `${displayClass(product.type)} ${product.name || ""}`.trim() : "Unresolved product"],
    repairable,
    status: repairable ? "Repairable" : "Review Required",
    selected: repairable,
    reason,
    details: reason,
    shellPlan: repairable ? shared : null,
    tokenStart: rep.start,
    tokenEnd: rep.start,
    recordStart: rep.start,
    recordEnd: rep.end,
  };
}
