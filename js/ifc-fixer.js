import {scanReferences} from "./ifc-loader.js?v=2.0";

const encoder = new TextEncoder();
// windows-1252 decodes one byte to one character, so text offsets equal byte offsets.
const decoder = new TextDecoder("windows-1252");

export class IfcRepairError extends Error {}

async function bytes(blob) { return new Uint8Array(await blob.arrayBuffer()); }

async function assertEqualRanges(source, sourceStart, sourceEnd, output, outputStart) {
  const chunkSize = 4 * 1024 * 1024;
  for (let offset = 0; offset < sourceEnd - sourceStart; offset += chunkSize) {
    const length = Math.min(chunkSize, sourceEnd - sourceStart - offset);
    const left = await bytes(source.slice(sourceStart + offset, sourceStart + offset + length));
    const right = await bytes(output.slice(outputStart + offset, outputStart + offset + length));
    if (left.length !== right.length || left.some((value, index) => value !== right[index])) {
      throw new IfcRepairError("Unexpected byte changes were detected outside the planned repair edits.");
    }
  }
}

const isShellIssue = issue => issue.issueType === "emptyClosedShell";

function contextEdits(repairs) {
  return repairs.filter(repair => !isShellIssue(repair)).map(repair => ({
    id: repair.id, start: repair.tokenStart, end: repair.tokenEnd, replacement: `#${repair.candidateContextId}`,
  }));
}

// Offsets of the top-level arguments inside the outer parentheses of one STEP record.
function argumentSpans(text) {
  const open = text.indexOf("(");
  const spans = [];
  let depth = 0, quoted = false, start = open + 1;
  for (let i = open + 1; i < text.length; i += 1) {
    const c = text[i];
    if (quoted) {
      if (c === "'" && text[i + 1] === "'") i += 1;
      else if (c === "'") quoted = false;
      continue;
    }
    if (c === "'") quoted = true;
    else if (c === "(") depth += 1;
    else if (c === ")") {
      if (depth === 0) { spans.push([start, i]); return spans; }
      depth -= 1;
    } else if (c === "," && depth === 0) { spans.push([start, i]); start = i + 1; }
  }
  throw new IfcRepairError("A planned record could not be parsed.");
}

function trimSpan(text, [start, end]) {
  while (start < end && /\s/.test(text[start])) start += 1;
  while (end > start && /\s/.test(text[end - 1])) end -= 1;
  return [start, end];
}

async function readRecord(file, op) {
  const text = decoder.decode(await file.slice(op.start, op.end).arrayBuffer());
  const head = text.match(/^#(\d+)\s*=\s*([A-Z0-9_]+)\s*\(/i);
  if (!head || Number(head[1]) !== op.id || head[2].toUpperCase() !== op.type || !text.trimEnd().endsWith(";")) {
    throw new IfcRepairError(`Record #${op.id} changed after analysis. Check the IFC again.`);
  }
  return text;
}

async function materializeShellPlan(file, plan) {
  const edits = [];
  for (const op of plan.ops) {
    const text = await readRecord(file, op);
    if (op.kind === "delete") {
      if (op.type === "IFCCLOSEDSHELL" && !/^#\d+\s*=\s*IFCCLOSEDSHELL\s*\(\s*\(\s*\)\s*\)\s*;$/i.test(text.trim())) {
        throw new IfcRepairError(`IfcClosedShell #${op.id} is no longer empty. Check the IFC again.`);
      }
      // Remove the line break after the record too, so no blank line is left.
      const after = decoder.decode(await file.slice(op.end, op.end + 2).arrayBuffer());
      const lineBreak = after.startsWith("\r\n") ? 2 : after.startsWith("\n") ? 1 : 0;
      edits.push({id: op.id, start: op.start, end: op.end + lineBreak, replacement: ""});
      continue;
    }
    const span = argumentSpans(text)[op.argIndex];
    if (!span) throw new IfcRepairError(`Record #${op.id} has fewer attributes than expected.`);
    const [start, end] = trimSpan(text, span);
    const value = text.slice(start, end);
    let replacement;
    if (op.kind === "setNull") {
      if (value !== `#${op.expectedRef}`) throw new IfcRepairError(`Record #${op.id} no longer references #${op.expectedRef}.`);
      replacement = "$";
    } else if (op.kind === "removeRefs") {
      const inner = value.match(/^\((.*)\)$/s)?.[1];
      const items = inner?.split(",").map(item => item.trim());
      if (!items || items.some(item => !/^#\d+$/.test(item))) throw new IfcRepairError(`Record #${op.id} does not hold a plain reference list.`);
      const remove = new Set(op.removeIds.map(id => `#${id}`));
      const kept = items.filter(item => !remove.has(item));
      if (kept.length !== op.keepCount || !kept.length || items.length - kept.length !== op.removeIds.length) {
        throw new IfcRepairError(`Record #${op.id} changed after analysis. Check the IFC again.`);
      }
      replacement = `(${kept.join(",")})`;
    } else throw new IfcRepairError(`Unknown repair operation for record #${op.id}.`);
    edits.push({id: op.id, start: op.start + start, end: op.start + end, replacement});
  }
  return edits;
}

export async function applyRepairs(file, selectedIssues, onProgress = () => {}) {
  const repairs = selectedIssues.filter(issue => issue.repairable && (issue.candidateContextId || issue.shellPlan))
    .sort((a, b) => a.tokenStart - b.tokenStart);
  if (!repairs.length) throw new IfcRepairError("Select at least one repairable issue.");
  const contextRepairs = repairs.filter(repair => !isShellIssue(repair));
  for (let index = 0; index < contextRepairs.length; index += 1) {
    const repair = contextRepairs[index];
    if (repair.tokenEnd <= repair.tokenStart) throw new IfcRepairError("The repair plan contains invalid or overlapping offsets.");
    const current = new TextDecoder("ascii").decode(await file.slice(repair.tokenStart, repair.tokenEnd).arrayBuffer());
    if (current !== "$") throw new IfcRepairError(`Representation #${repair.id} changed after analysis. Check the IFC again.`);
    if (index % 250 === 0) {
      onProgress({stage: "Validating repair plan", current: index + 1, total: contextRepairs.length, unit: "items"});
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }

  const edits = contextEdits(repairs);
  const selectedIds = new Set(repairs.map(repair => repair.id));
  const plans = [...new Set(repairs.filter(isShellIssue).map(repair => repair.shellPlan))];
  for (const plan of plans) {
    if (plan.issueIds.some(id => !selectedIds.has(id))) {
      throw new IfcRepairError("Empty-shell repairs in one file share records and must be repaired together.");
    }
    onProgress({stage: "Planning empty IfcClosedShell removal", current: 0, total: plan.ops.length, unit: "items"});
    edits.push(...await materializeShellPlan(file, plan));
  }
  edits.sort((a, b) => a.start - b.start);
  for (let index = 1; index < edits.length; index += 1) {
    if (edits[index].start < edits[index - 1].end) throw new IfcRepairError("The repair plan contains invalid or overlapping offsets.");
  }

  const parts = []; let cursor = 0;
  for (let index = 0; index < edits.length; index += 1) {
    const edit = edits[index];
    parts.push(file.slice(cursor, edit.start));
    if (edit.replacement) parts.push(encoder.encode(edit.replacement));
    cursor = edit.end;
    if (index % 250 === 0) onProgress({stage: "Applying targeted repairs", current: index + 1, total: edits.length, unit: "items"});
  }
  parts.push(file.slice(cursor));
  const output = new Blob(parts, {type: "application/x-step"});
  return {output, repairs, edits};
}

export function verifyRepairedModel(model, repairs) {
  let successfulChanges = 0;
  for (const repair of repairs) {
    if (isShellIssue(repair)) {
      const plan = repair.shellPlan;
      const leftover = plan.deletedIds.filter(id => model.entities.has(id));
      if (leftover.length) throw new IfcRepairError(`Removed records are still present after repair: #${leftover.slice(0, 5).join(", #")}.`);
      const representation = model.detailed.get(repair.id);
      if (representation) {
        const removed = plan.ops.find(op => op.id === repair.id)?.removeIds || [];
        if (!representation.itemIds.length || removed.some(id => representation.itemIds.includes(id))) {
          throw new IfcRepairError(`Representation #${repair.id} still holds empty geometry after repair.`);
        }
      }
      successfulChanges += 1;
      continue;
    }
    const representation = model.detailed.get(repair.id);
    if (representation?.type !== "IFCSHAPEREPRESENTATION") {
      throw new IfcRepairError(`Repaired representation #${repair.id} is missing from the output model.`);
    }
    if (representation.firstToken !== `#${repair.candidateContextId}`) {
      throw new IfcRepairError(`Representation #${repair.id} does not reference the planned context after repair.`);
    }
    const context = model.detailed.get(repair.candidateContextId);
    if (!context || !["IFCGEOMETRICREPRESENTATIONCONTEXT", "IFCGEOMETRICREPRESENTATIONSUBCONTEXT"].includes(context.type)) {
      throw new IfcRepairError(`Context #${repair.candidateContextId} is not a geometric representation context in the output IFC.`);
    }
    successfulChanges += 1;
  }
  return {expectedChanges: repairs.length, successfulChanges, unexpectedChanges: 0};
}

// After removing records, no remaining record may still point at one of them.
export async function verifyNoDanglingReferences(output, repairs, onProgress = () => {}) {
  const deleted = new Set(repairs.filter(isShellIssue).flatMap(repair => repair.shellPlan.deletedIds));
  if (!deleted.size) return {danglingReferences: 0};
  const users = await scanReferences(output, deleted, onProgress);
  if (users.size) {
    const [id, list] = users.entries().next().value;
    throw new IfcRepairError(`Record #${list[0].id} still references removed record #${id}.`);
  }
  return {danglingReferences: 0};
}

export async function verifyRepairs(source, output, repairs, onProgress = () => {}, edits = contextEdits(repairs)) {
  const planned = [...edits].sort((a, b) => a.start - b.start);
  const expectedSize = source.size + planned.reduce((sum, edit) => sum + encoder.encode(edit.replacement).length - (edit.end - edit.start), 0);
  if (output.size !== expectedSize) throw new IfcRepairError("The repaired IFC size does not match the targeted repair plan.");
  let sourceCursor = 0;
  let outputCursor = 0;
  for (let index = 0; index < planned.length; index += 1) {
    const edit = planned[index];
    await assertEqualRanges(source, sourceCursor, edit.start, output, outputCursor);
    outputCursor += edit.start - sourceCursor;
    const replacement = encoder.encode(edit.replacement);
    const actualReplacement = await bytes(output.slice(outputCursor, outputCursor + replacement.length));
    if (actualReplacement.length !== replacement.length ||
        actualReplacement.some((value, offset) => value !== replacement[offset])) {
      throw new IfcRepairError(`Replacement verification failed for record #${edit.id}.`);
    }
    sourceCursor = edit.end;
    outputCursor += replacement.length;
    if (index % 25 === 0) {
      onProgress({stage: "Comparing unchanged IFC bytes", current: index + 1, total: planned.length, unit: "items"});
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }
  await assertEqualRanges(source, sourceCursor, source.size, output, outputCursor);
  const tail = decoder.decode(await output.slice(Math.max(0, output.size - 1024 * 1024)).arrayBuffer());
  if (!/END-ISO-10303-21\s*;/i.test(tail)) throw new IfcRepairError("The repaired IFC footer could not be verified.");
  return {
    passed: true,
    repaired: repairs.length,
    expectedChanges: repairs.length,
    successfulChanges: repairs.length,
    unexpectedChanges: 0,
    outputSize: output.size,
  };
}
