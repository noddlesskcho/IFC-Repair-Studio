import {openAsBlob} from "node:fs";
import {basename, resolve} from "node:path";

import {analyzeIfc} from "../js/ifc-analyzer.js";
import {applyRepairs, verifyRepairs} from "../js/ifc-fixer.js";
import {loadIfc} from "../js/ifc-loader.js";

const input = process.argv[2];
if (!input) {
  console.error("Usage: node scripts/check-browser-ifc.mjs <input.ifc>");
  process.exit(2);
}

const path = resolve(input);
const file = await openAsBlob(path);
Object.defineProperty(file, "name", {value: basename(path)});
let lastPercent = -1;
const progress = ({stage, current = 0, total = 0}) => {
  const percent = total ? Math.floor(current * 100 / total) : 0;
  if (percent >= lastPercent + 10 || percent === 100) {
    console.error(`${stage}: ${percent}%`);
    lastPercent = percent;
  }
};

const model = await loadIfc(file, progress);
lastPercent = -1;
const analysis = await analyzeIfc(model, progress);
let verification = null;
if (process.argv.includes("--verify-repair") && analysis.repairable) {
  lastPercent = -1;
  const selected = analysis.issues.filter(issue => issue.repairable);
  const repaired = await applyRepairs(file, selected, progress);
  verification = await verifyRepairs(file, repaired.output, repaired.repairs, progress);
}
const signatures = {};
for (const issue of analysis.issues) {
  const key = `${issue.identifier} / ${issue.representationType}`;
  const current = signatures[key] || {detected: 0, repairable: 0};
  current.detected += 1;
  if (issue.repairable) current.repairable += 1;
  signatures[key] = current;
}
console.log(JSON.stringify({
  schema: analysis.schema,
  productsScanned: analysis.productsScanned,
  representationsScanned: analysis.representationsScanned,
  detected: analysis.issues.length,
  repairable: analysis.repairable,
  reportOnly: analysis.reviewOnly,
  verification,
  signatures,
}, null, 2));
