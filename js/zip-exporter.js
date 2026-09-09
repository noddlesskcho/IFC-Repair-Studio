const UINT32_MAX = 0xffffffff;
const CHUNK_SIZE = 4 * 1024 * 1024;
const encoder = new TextEncoder();

const crcTable = new Uint32Array(256);
for (let value = 0; value < 256; value += 1) {
  let crc = value;
  for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  crcTable[value] = crc >>> 0;
}

function safeName(name) {
  const cleaned = String(name || "repaired.ifc").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_");
  return cleaned.replace(/^\.+$/, "repaired.ifc");
}

function uniqueNames(entries) {
  const used = new Set();
  return entries.map(entry => {
    const original = safeName(entry.name);
    const dot = original.lastIndexOf(".");
    const stem = dot > 0 ? original.slice(0, dot) : original;
    const extension = dot > 0 ? original.slice(dot) : "";
    let name = original;
    let suffix = 2;
    while (used.has(name.toLowerCase())) name = `${stem}_${suffix++}${extension}`;
    used.add(name.toLowerCase());
    return {...entry, name};
  });
}

async function crc32Blob(blob, onChunk) {
  let crc = 0xffffffff;
  for (let offset = 0; offset < blob.size; offset += CHUNK_SIZE) {
    const bytes = new Uint8Array(await blob.slice(offset, offset + CHUNK_SIZE).arrayBuffer());
    for (const byte of bytes) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    onChunk(bytes.byteLength);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function zipDate(date = new Date()) {
  const year = Math.max(1980, date.getFullYear());
  return {
    time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2),
    date: ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
  };
}

function localHeader(nameBytes, size, crc, modified) {
  const buffer = new ArrayBuffer(30);
  const view = new DataView(buffer);
  view.setUint32(0, 0x04034b50, true);
  view.setUint16(4, 20, true);
  view.setUint16(6, 0x0800, true);
  view.setUint16(8, 0, true);
  view.setUint16(10, modified.time, true);
  view.setUint16(12, modified.date, true);
  view.setUint32(14, crc, true);
  view.setUint32(18, size, true);
  view.setUint32(22, size, true);
  view.setUint16(26, nameBytes.length, true);
  view.setUint16(28, 0, true);
  return buffer;
}

function centralHeader(record) {
  const buffer = new ArrayBuffer(46);
  const view = new DataView(buffer);
  view.setUint32(0, 0x02014b50, true);
  view.setUint16(4, 20, true);
  view.setUint16(6, 20, true);
  view.setUint16(8, 0x0800, true);
  view.setUint16(10, 0, true);
  view.setUint16(12, record.modified.time, true);
  view.setUint16(14, record.modified.date, true);
  view.setUint32(16, record.crc, true);
  view.setUint32(20, record.size, true);
  view.setUint32(24, record.size, true);
  view.setUint16(28, record.nameBytes.length, true);
  view.setUint16(30, 0, true);
  view.setUint16(32, 0, true);
  view.setUint16(34, 0, true);
  view.setUint16(36, 0, true);
  view.setUint32(38, 0, true);
  view.setUint32(42, record.offset, true);
  return buffer;
}

function endRecord(entryCount, centralSize, centralOffset) {
  const buffer = new ArrayBuffer(22);
  const view = new DataView(buffer);
  view.setUint32(0, 0x06054b50, true);
  view.setUint16(4, 0, true);
  view.setUint16(6, 0, true);
  view.setUint16(8, entryCount, true);
  view.setUint16(10, entryCount, true);
  view.setUint32(12, centralSize, true);
  view.setUint32(16, centralOffset, true);
  view.setUint16(20, 0, true);
  return buffer;
}

export async function createRepairedZip(entries, onProgress = () => {}) {
  if (!entries.length) throw new Error("No repaired IFC files are available for the ZIP archive.");
  if (entries.length > 0xffff) throw new Error("The ZIP archive supports up to 65,535 repaired IFC files.");
  const namedEntries = uniqueNames(entries);
  const totalBytes = namedEntries.reduce((sum, entry) => sum + entry.blob.size, 0);
  let bytesRead = 0;
  let offset = 0;
  const parts = [];
  const records = [];

  for (const entry of namedEntries) {
    if (entry.blob.size > UINT32_MAX) throw new Error(`${entry.name} exceeds the 4 GB ZIP entry limit.`);
    const nameBytes = encoder.encode(entry.name);
    const crc = await crc32Blob(entry.blob, count => {
      bytesRead += count;
      onProgress({stage: `Packaging ${entry.name}`, current: bytesRead, total: totalBytes, unit: "bytes"});
    });
    const modified = zipDate(entry.lastModified ? new Date(entry.lastModified) : new Date());
    const header = localHeader(nameBytes, entry.blob.size, crc, modified);
    if (offset + header.byteLength + nameBytes.byteLength + entry.blob.size > UINT32_MAX) {
      throw new Error("The repaired files exceed the 4 GB ZIP archive limit.");
    }
    records.push({nameBytes, size: entry.blob.size, crc, modified, offset});
    parts.push(header, nameBytes, entry.blob);
    offset += header.byteLength + nameBytes.byteLength + entry.blob.size;
  }

  const centralOffset = offset;
  for (const record of records) {
    const header = centralHeader(record);
    parts.push(header, record.nameBytes);
    offset += header.byteLength + record.nameBytes.byteLength;
  }
  const centralSize = offset - centralOffset;
  if (offset + 22 > UINT32_MAX) throw new Error("The repaired files exceed the 4 GB ZIP archive limit.");
  parts.push(endRecord(records.length, centralSize, centralOffset));
  return new Blob(parts, {type: "application/zip"});
}

export function repairedArchiveName() {
  return "IFC-SG_IfcShapeRepresentation_repaired_files.zip";
}
