const encoder = new TextEncoder();

export class IfcRepairError extends Error {}

async function bytes(blob) { return new Uint8Array(await blob.arrayBuffer()); }

export async function applyRepairs(file, selectedIssues, onProgress = () => {}) {
  const repairs = selectedIssues.filter(issue => issue.repairable && issue.candidateContextId).sort((a, b) => a.tokenStart - b.tokenStart);
  if (!repairs.length) throw new IfcRepairError("Select at least one repairable issue.");
  let previousEnd = -1;
  for (let index = 0; index < repairs.length; index += 1) {
    const repair = repairs[index];
    if (repair.tokenStart < previousEnd || repair.tokenEnd <= repair.tokenStart) throw new IfcRepairError("The repair plan contains invalid or overlapping offsets.");
    const current = new TextDecoder("ascii").decode(await file.slice(repair.tokenStart, repair.tokenEnd).arrayBuffer());
    if (current !== "$") throw new IfcRepairError(`Representation #${repair.id} changed after analysis. Check the IFC again.`);
    previousEnd = repair.tokenEnd;
    if (index % 250 === 0) {
      onProgress({stage: "Validating repair plan", current: index + 1, total: repairs.length, unit: "items"});
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }

  const parts = []; let cursor = 0;
  for (let index = 0; index < repairs.length; index += 1) {
    const repair = repairs[index];
    parts.push(file.slice(cursor, repair.tokenStart));
    parts.push(encoder.encode(`#${repair.candidateContextId}`));
    cursor = repair.tokenEnd;
    if (index % 250 === 0) onProgress({stage: "Applying targeted repairs", current: index + 1, total: repairs.length, unit: "items"});
  }
  parts.push(file.slice(cursor));
  const output = new Blob(parts, {type: "application/x-step"});
  return {output, repairs};
}

export async function verifyRepairs(source, output, repairs, onProgress = () => {}) {
  const expectedSize = source.size + repairs.reduce((sum, repair) => sum + `#${repair.candidateContextId}`.length - 1, 0);
  if (output.size !== expectedSize) throw new IfcRepairError("The repaired IFC size does not match the targeted repair plan.");
  let cumulativeDelta = 0;
  for (let index = 0; index < repairs.length; index += 1) {
    const repair = repairs[index];
    const original = await bytes(source.slice(repair.recordStart, repair.recordEnd));
    const relativeStart = repair.tokenStart - repair.recordStart;
    const relativeEnd = repair.tokenEnd - repair.recordStart;
    const replacement = encoder.encode(`#${repair.candidateContextId}`);
    const expected = new Uint8Array(original.length - (relativeEnd - relativeStart) + replacement.length);
    expected.set(original.slice(0, relativeStart), 0);
    expected.set(replacement, relativeStart);
    expected.set(original.slice(relativeEnd), relativeStart + replacement.length);
    const outputStart = repair.recordStart + cumulativeDelta;
    const actual = await bytes(output.slice(outputStart, outputStart + expected.length));
    if (actual.length !== expected.length || actual.some((value, offset) => value !== expected[offset])) {
      throw new IfcRepairError(`Targeted verification failed for representation #${repair.id}.`);
    }
    cumulativeDelta += replacement.length - (relativeEnd - relativeStart);
    if (index % 250 === 0) {
      onProgress({stage: "Verifying repaired records", current: index + 1, total: repairs.length, unit: "items"});
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }
  const tail = new TextDecoder("windows-1252").decode(await output.slice(Math.max(0, output.size - 1024 * 1024)).arrayBuffer());
  if (!/END-ISO-10303-21\s*;/i.test(tail)) throw new IfcRepairError("The repaired IFC footer could not be verified.");
  return {passed: true, repaired: repairs.length, unexpectedChanges: 0, outputSize: output.size};
}
