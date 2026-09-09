import {openAsBlob} from "node:fs";
import {pipeline} from "node:stream/promises";
import {Readable} from "node:stream";
import {createWriteStream} from "node:fs";

import {analyzeIfc} from "../js/ifc-analyzer.js";
import {applyRepairs, verifyRepairedModel, verifyRepairs} from "../js/ifc-fixer.js";
import {loadIfc} from "../js/ifc-loader.js";

const [sourcePath, outputPath] = process.argv.slice(2);
if (!sourcePath) {
  throw new Error("Usage: node scripts/acceptance-browser.mjs <source.ifc> [output.ifc]");
}

function named(blob, name) {
  Object.defineProperty(blob, "name", {value: name});
  return blob;
}

const source = named(await openAsBlob(sourcePath), sourcePath);
const sourceModel = await loadIfc(source);
const original = await analyzeIfc(sourceModel);
const selected = original.issues.filter(issue => issue.repairable);
const {output, repairs} = await applyRepairs(source, selected);
const byteVerification = await verifyRepairs(source, output, repairs);
named(output, outputPath || "repaired.ifc");
const outputModel = await loadIfc(output);
const modelVerification = verifyRepairedModel(outputModel, repairs);
const repaired = await analyzeIfc(outputModel);

if (outputPath) {
  await pipeline(Readable.fromWeb(output.stream()), createWriteStream(outputPath, {flags: "wx"}));
}

console.log(JSON.stringify({
  sourceBytes: source.size,
  outputBytes: output.size,
  original: {
    representationsScanned: original.representationsScanned,
    supportedMissing: original.issues.length,
    counts: original.counts,
    repairable: original.repairable,
    reviewRequired: original.reviewOnly,
  },
  verification: {...byteVerification, ...modelVerification},
  repaired: {
    supportedMissing: repaired.issues.length,
    counts: repaired.counts,
    repairable: repaired.repairable,
    reviewRequired: repaired.reviewOnly,
  },
  outputPath: outputPath || null,
}, null, 2));
