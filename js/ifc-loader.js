const decoder = new TextDecoder("windows-1252");
const DETAILED_TYPES = new Set([
  "IFCPROJECT",
  "IFCGEOMETRICREPRESENTATIONCONTEXT",
  "IFCGEOMETRICREPRESENTATIONSUBCONTEXT",
  "IFCSHAPEREPRESENTATION",
  "IFCPRODUCTDEFINITIONSHAPE",
  "IFCSHAPEASPECT",
  "IFCPRESENTATIONLAYERASSIGNMENT",
  "IFCPRESENTATIONLAYERWITHSTYLE",
  "IFCREPRESENTATIONMAP",
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

function parseCapturedRecord(bytes, start, end, truncated = false) {
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
    id: Number(prefix[1]), type: prefix[2].toUpperCase(), args, start, end, truncated,
    firstToken: text.slice(firstStart, firstEnd),
    firstTokenStart: start + firstStart,
    firstTokenEnd: start + firstEnd,
  };
}

function grow(buffer, limit = 64 * 1024) {
  const next = new Uint8Array(Math.min(buffer.length * 2, limit));
  next.set(buffer); return next;
}

// Reference ids outside quoted strings and comments, so a name such as 'Panel #12' is not a reference.
export function codeRefs(value = "") {
  return refs(String(value).replace(/'(?:[^']|'')*'/g, "''").replace(/\/\*[\s\S]*?\*\//g, ""));
}

function compactDetailedRecord(record) {
  if (record.type === "IFCSHAPEREPRESENTATION") {
    const itemIds = codeRefs(record.args[3]);
    record.itemIds = itemIds;
    record.args = [record.args[0], record.args[1], record.args[2], itemIds[0] ? `#${itemIds[0]}` : ""];
  } else if (record.type === "IFCPRODUCTDEFINITIONSHAPE") {
    record.args = [record.args[0], record.args[1], record.args[2]];
  } else if (record.type === "IFCSHAPEASPECT") {
    record.args = [record.args[0], record.args[1], record.args[2], record.args[3], record.args[4]];
  } else if (["IFCPRESENTATIONLAYERASSIGNMENT", "IFCPRESENTATIONLAYERWITHSTYLE"].includes(record.type)) {
    record.args = [record.args[0], record.args[1], record.args[2], record.args[3]];
  } else if (record.type === "IFCREPRESENTATIONMAP") {
    record.args = [record.args[0], record.args[1]];
  } else if (record.type === "IFCPROJECT") {
    record.args = Array.from({length: 8}, (_, index) => record.args[index]);
  }
  return record;
}

// Streams every complete STEP entity record and hands the parsed record to onRecord.
async function streamRecords(file, onRecord, onProgress, stage, CAPTURE_LIMIT = 64 * 1024) {
  const reader = file.stream().getReader();
  let absolute = 0, lineHasContent = false, inRecord = false;
  let recordStart = 0, recordLength = 0, capture = new Uint8Array(1024);
  let quoted = false, comment = false, lastByte = -1, lastYield = performance.now();

  const finishRecord = (end) => {
    const record = parseCapturedRecord(capture.slice(0, Math.min(recordLength, CAPTURE_LIMIT)), recordStart, end, recordLength > CAPTURE_LIMIT);
    if (record) onRecord(record);
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
          if (recordLength >= capture.length) capture = grow(capture, CAPTURE_LIMIT);
          capture[recordLength] = byte;
        }
        recordLength += 1;
        if (comment) {
          if (lastByte === 42 && byte === 47) comment = false;
        } else if (quoted) {
          if (byte === 39) {
            if (next === 39) { // doubled apostrophe
              if (recordLength < CAPTURE_LIMIT) {
                if (recordLength >= capture.length) capture = grow(capture, CAPTURE_LIMIT);
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
      onProgress({stage, current: absolute, total: file.size, unit: "bytes"});
      await new Promise(resolve => setTimeout(resolve, 0));
      lastYield = now;
    }
  }
  if (inRecord) throw new IfcInputError("The IFC contains an unterminated STEP entity record.");
}

export async function loadIfc(file, onProgress = () => {}, fileName = file?.name) {
  if (!file || !fileName?.toLowerCase().endsWith(".ifc")) {
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
  const typeCandidates = [];
  const emptyShells = new Map();
  const brepOuters = new Map();

  await streamRecords(file, record => {
    entities.set(record.id, record.type);
    if (DETAILED_TYPES.has(record.type)) detailed.set(record.id, compactDetailedRecord(record));
    else if (record.type === "IFCCLOSEDSHELL") {
      if (!record.truncated && record.args.length === 1 && /^\(\s*\)$/.test(record.args[0])) {
        emptyShells.set(record.id, {id: record.id, start: record.start, end: record.end});
      }
    } else if (record.type === "IFCFACETEDBREP") {
      const outer = codeRefs(record.args[0])[0];
      if (outer) brepOuters.set(record.id, outer);
    }
    if (!DETAILED_TYPES.has(record.type) && record.args.length >= 7 && /^IFC[A-Z0-9_]+$/.test(record.type) && /^#\d+$/.test(record.args[6] || "")) {
      // Keep ObjectType (Revit family:type) and Tag (Revit element ID) so users can find the element.
      record.args = [record.args[0], undefined, record.args[2], undefined, record.args[4], undefined, record.args[6], record.args[7]];
      productCandidates.push(record);
    } else if (/(TYPE|STYLE)$/.test(record.type) && /^\(\s*#/.test(record.args[6] || "")) {
      // Type objects own IfcRepresentationMap geometry: RepresentationMaps is attribute 7, Tag attribute 8.
      typeCandidates.push({id: record.id, type: record.type, globalId: stepString(record.args[0]), name: stepString(record.args[2]),
        tag: stepString(record.args[7]), mapIds: codeRefs(record.args[6])});
    }
  }, onProgress, "Reading IFC records");
  onProgress({stage: "IFC records loaded", current: file.size, total: file.size, unit: "bytes"});
  return {file, schema, entities, detailed, productCandidates, typeCandidates, emptyShells, brepOuters};
}

// Finds every record that references one of targetIds, with the argument positions of each reference.
export async function scanReferences(file, targetIds, onProgress = () => {}) {
  const users = new Map();
  if (!targetIds.size) return users;
  await streamRecords(file, record => {
    // Cheap first test on the raw arguments; most records reference none of the targets.
    if (!record.args.some(arg => refs(arg).some(id => targetIds.has(id)))) return;
    record.args.forEach((arg, argIndex) => {
      for (const id of codeRefs(arg)) {
        if (!targetIds.has(id)) continue;
        if (!users.has(id)) users.set(id, []);
        const list = users.get(id);
        let user = list.find(entry => entry.id === record.id);
        if (!user) {
          user = {id: record.id, type: record.type, start: record.start, end: record.end, truncated: record.truncated, argIndexes: new Set(), args: record.args};
          list.push(user);
        }
        user.argIndexes.add(argIndex);
      }
    });
    // Full capture: a reference beyond the normal 64 KB capture must still be found.
  }, onProgress, "Tracing empty geometry references", Number.MAX_SAFE_INTEGER);
  return users;
}
