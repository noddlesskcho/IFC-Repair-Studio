const decoder = new TextDecoder("windows-1252");
const DETAILED_TYPES = new Set([
  "IFCPROJECT",
  "IFCGEOMETRICREPRESENTATIONCONTEXT",
  "IFCGEOMETRICREPRESENTATIONSUBCONTEXT",
  "IFCSHAPEREPRESENTATION",
  "IFCPRODUCTDEFINITIONSHAPE",
]);

export class IfcInputError extends Error {}

export function splitStepArguments(value) {
  const result = [];
  let start = 0, depth = 0, quoted = false, comment = false;
  for (let i = 0; i < value.length; i += 1) {
    const c = value[i], n = value[i + 1];
    if (comment) {
      if (c === "*" && n === "/") { comment = false; i += 1; }
      continue;
    }
    if (quoted) {
      if (c === "'" && n === "'") { i += 1; continue; }
      if (c === "'") quoted = false;
      continue;
    }
    if (c === "/" && n === "*") { comment = true; i += 1; continue; }
    if (c === "'") { quoted = true; continue; }
    if (c === "(") depth += 1;
    else if (c === ")") depth -= 1;
    else if (c === "," && depth === 0) {
      result.push(value.slice(start, i).trim()); start = i + 1;
    }
  }
  result.push(value.slice(start).trim());
  return result;
}

export function refs(value = "") {
  return [...value.matchAll(/#(\d+)/g)].map(match => Number(match[1]));
}

export function stepString(value) {
  if (!value || value === "$" || value === "*") return null;
  const match = value.match(/^'(.*)'$/s);
  return match ? match[1].replace(/''/g, "'") : value;
}

function parseCapturedRecord(bytes, start, end) {
  const text = decoder.decode(bytes);
  const prefix = text.match(/^\s*#(\d+)\s*=\s*([A-Z0-9_]+)\s*\(/i);
  if (!prefix) return null;
  const open = text.indexOf("(", prefix.index + prefix[0].length - 1);
  const close = text.lastIndexOf(")");
  const args = close > open ? splitStepArguments(text.slice(open + 1, close)) : [];
  let firstStart = open + 1;
  while (/\s/.test(text[firstStart] || "")) firstStart += 1;
  let firstEnd = firstStart;
  while (firstEnd < text.length && !/[\s,]/.test(text[firstEnd])) firstEnd += 1;
  return {
    id: Number(prefix[1]), type: prefix[2].toUpperCase(), args, start, end,
    firstToken: text.slice(firstStart, firstEnd),
    firstTokenStart: start + firstStart,
    firstTokenEnd: start + firstEnd,
  };
}

function grow(buffer) {
  const next = new Uint8Array(Math.min(buffer.length * 2, 64 * 1024));
  next.set(buffer); return next;
}

function compactDetailedRecord(record) {
  if (record.type === "IFCSHAPEREPRESENTATION") {
    const firstItem = refs(record.args[3])[0];
    record.args = [record.args[0], record.args[1], record.args[2], firstItem ? `#${firstItem}` : ""];
  } else if (record.type === "IFCPRODUCTDEFINITIONSHAPE") {
    record.args = [record.args[0], record.args[1], record.args[2]];
  } else if (record.type === "IFCPROJECT") {
    record.args = Array.from({length: 8}, (_, index) => record.args[index]);
  }
  return record;
}

export async function loadIfc(file, onProgress = () => {}) {
  if (!file || !file.name?.toLowerCase().endsWith(".ifc")) {
    throw new IfcInputError("Select an uncompressed .ifc file.");
  }
  if (!file.size) throw new IfcInputError("The selected IFC is empty.");

  const header = decoder.decode(await file.slice(0, Math.min(file.size, 1024 * 1024)).arrayBuffer());
  const schema = header.match(/FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'/i)?.[1]?.toUpperCase() || "Unknown";
  if (!/ISO-10303-21\s*;/i.test(header) || !/\bDATA\s*;/i.test(header)) {
    throw new IfcInputError("The file does not contain a valid IFC STEP header and DATA section.");
  }
  const footer = decoder.decode(await file.slice(Math.max(0, file.size - 1024 * 1024)).arrayBuffer());
  if (!/END-ISO-10303-21\s*;/i.test(footer)) {
    throw new IfcInputError("The IFC footer is missing or truncated.");
  }

  const entities = new Map();
  const detailed = new Map();
  const productCandidates = [];
  const reader = file.stream().getReader();
  let absolute = 0, lineHasContent = false, inRecord = false;
  let recordStart = 0, recordLength = 0, capture = new Uint8Array(1024);
  let quoted = false, comment = false, lastByte = -1, lastYield = performance.now();
  const CAPTURE_LIMIT = 64 * 1024;

  const finishRecord = (end) => {
    const record = parseCapturedRecord(capture.slice(0, Math.min(recordLength, CAPTURE_LIMIT)), recordStart, end);
    if (record) {
      entities.set(record.id, record.type);
      if (DETAILED_TYPES.has(record.type)) detailed.set(record.id, compactDetailedRecord(record));
      if (!DETAILED_TYPES.has(record.type) && record.args.length >= 7 && /^IFC[A-Z0-9_]+$/.test(record.type) && /^#\d+$/.test(record.args[6] || "")) {
        record.args = [record.args[0], undefined, record.args[2], undefined, undefined, undefined, record.args[6]];
        productCandidates.push(record);
      }
    }
    inRecord = false; quoted = false; comment = false; recordLength = 0;
    capture = new Uint8Array(1024);
  };

  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    for (let i = 0; i < value.length; i += 1) {
      const byte = value[i], next = value[i + 1] ?? -1;
      if (!inRecord) {
        if (byte === 35 && !lineHasContent) { // # at the first non-whitespace position
          inRecord = true; recordStart = absolute + i; recordLength = 0;
        } else if (byte === 10 || byte === 13) lineHasContent = false;
        else if (byte !== 32 && byte !== 9) lineHasContent = true;
      }
      if (inRecord) {
        if (recordLength < CAPTURE_LIMIT) {
          if (recordLength >= capture.length) capture = grow(capture);
          capture[recordLength] = byte;
        }
        recordLength += 1;
        if (comment) {
          if (lastByte === 42 && byte === 47) comment = false;
        } else if (quoted) {
          if (byte === 39) {
            if (next === 39) { // doubled apostrophe
              if (recordLength < CAPTURE_LIMIT) {
                if (recordLength >= capture.length) capture = grow(capture);
                capture[recordLength] = next;
              }
              recordLength += 1; i += 1;
            } else quoted = false;
          }
        } else if (lastByte === 47 && byte === 42) comment = true;
        else if (byte === 39) quoted = true;
        else if (byte === 59) {
          finishRecord(absolute + i + 1);
          // STEP permits the next entity to begin after whitespace on the same line.
          lineHasContent = false;
        }
      }
      lastByte = byte;
    }
    absolute += value.length;
    const now = performance.now();
    if (now - lastYield > 40) {
      onProgress({stage: "Reading IFC records", current: absolute, total: file.size, unit: "bytes"});
      await new Promise(resolve => setTimeout(resolve, 0));
      lastYield = now;
    }
  }
  if (inRecord) throw new IfcInputError("The IFC contains an unterminated STEP entity record.");
  onProgress({stage: "IFC records loaded", current: file.size, total: file.size, unit: "bytes"});
  return {file, schema, entities, detailed, productCandidates};
}
