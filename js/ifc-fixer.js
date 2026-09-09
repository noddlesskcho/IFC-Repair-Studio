const encoder = new TextEncoder();

export class IfcRepairError extends Error {}

async function bytes(blob) { return new Uint8Array(await blob.arrayBuffer()); }

async function assertEqualRanges(source, sourceStart, sourceEnd, output, outputStart) {
  const chunkSize = 4 * 1024 * 1024;
  for (let offset = 0; offset < sourceEnd - sourceStart; offset += chunkSize) {
    const length = Math.min(chunkSize, sourceEnd - sourceStart - offset);
    const left = await bytes(source.slice(sourceStart + offset, sourceStart + offset + length));
    const right = await bytes(output.slice(outputStart + offset, outputStart + offset + length));
    if (left.length !== right.length || left.some((value, index) => value !== right[index])) {
      throw new IfcRepairError("Unexpected byte changes were detected outside the planned ContextOfItems tokens.");
    }
  }
}

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

export function verifyRepairedModel(model, repairs) {
  let successfulChanges = 0;
  for (const repair of repairs) {
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

export async function verifyRepairs(source, output, repairs, onProgress = () => {}) {
  const expectedSize = source.size + repairs.reduce((sum, repair) => sum + `#${repair.candidateContextId}`.length - 1, 0);
  if (output.size !== expectedSize) throw new IfcRepairError("The repaired IFC size does not match the targeted repair plan.");
  let sourceCursor = 0;
  let outputCursor = 0;
  let cumulativeDelta = 0;
  for (let index = 0; index < repairs.length; index += 1) {
    const repair = repairs[index];
    const outputTokenStart = repair.tokenStart + cumulativeDelta;
    await assertEqualRanges(source, sourceCursor, repair.tokenStart, output, outputCursor);
    const replacement = encoder.encode(`#${repair.candidateContextId}`);
    const actualReplacement = await bytes(output.slice(outputTokenStart, outputTokenStart + replacement.length));
    if (actualReplacement.length !== replacement.length ||
        actualReplacement.some((value, offset) => value !== replacement[offset])) {
      throw new IfcRepairError(`Replacement token verification failed for representation #${repair.id}.`);
    }
    sourceCursor = repair.tokenEnd;
    outputCursor = outputTokenStart + replacement.length;
    cumulativeDelta += replacement.length - (repair.tokenEnd - repair.tokenStart);
    if (index % 25 === 0) {
      onProgress({stage: "Comparing unchanged IFC bytes", current: index + 1, total: repairs.length, unit: "items"});
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  }
  await assertEqualRanges(source, sourceCursor, source.size, output, outputCursor);
  const tail = new TextDecoder("windows-1252").decode(await output.slice(Math.max(0, output.size - 1024 * 1024)).arrayBuffer());
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
