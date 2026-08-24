import {loadIfc} from "./ifc-loader.js?v=1.0.0-r3";
import {analyzeIfc} from "./ifc-analyzer.js?v=1.0.0-r3";
import {applyRepairs, verifyRepairs} from "./ifc-fixer.js?v=1.0.0-r3";
import {downloadBlob, repairedFileName} from "./ifc-exporter.js?v=1.0.0-r3";
import {elements, renderResults, resetUi, setStep, showCompletion, showError, showFile, updateProgress, updateRepairButton} from "./ui.js?v=1.0.0-r3";

const state = {file: null, analysis: null, output: null, outputName: null, busy: false};

function setBusy(value) {
  state.busy = value; elements.choose.disabled = value; elements.repair.disabled = value || !state.analysis?.repairable;
}

async function processFile(file) {
  if (state.busy) return;
  resetUi(); state.file = file; state.analysis = null; state.output = null; state.outputName = null;
  showFile(file); setStep(2); setBusy(true);
  try {
    const model = await loadIfc(file, updateProgress);
    state.analysis = await analyzeIfc(model, updateProgress);
    renderResults(state.analysis, () => updateRepairButton(state.analysis));
  } catch (error) { showError(error); }
  finally { setBusy(false); if (state.analysis) updateRepairButton(state.analysis); }
}

async function repairSelected() {
  if (state.busy || !state.file || !state.analysis) return;
  setBusy(true);
  try {
    const selected = state.analysis.issues.filter(issue => issue.selected && issue.repairable);
    const {output, repairs} = await applyRepairs(state.file, selected, updateProgress);
    const result = await verifyRepairs(state.file, output, repairs, updateProgress);
    state.output = output; state.outputName = repairedFileName(state.file.name); showCompletion(result, state.outputName);
  } catch (error) { showError(error); }
  finally { setBusy(false); }
}

function restart() {
  state.file = null; state.analysis = null; state.output = null; state.outputName = null; resetUi();
}

elements.choose.addEventListener("click", () => elements.input.click());
elements.drop.addEventListener("click", () => elements.input.click());
elements.drop.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); elements.input.click(); } });
elements.input.addEventListener("change", () => { if (elements.input.files[0]) processFile(elements.input.files[0]); });
for (const name of ["dragenter", "dragover"]) elements.drop.addEventListener(name, event => { event.preventDefault(); elements.drop.classList.add("drag"); });
for (const name of ["dragleave", "drop"]) elements.drop.addEventListener(name, event => { event.preventDefault(); elements.drop.classList.remove("drag"); });
elements.drop.addEventListener("drop", event => { const file = event.dataTransfer.files[0]; if (file) processFile(file); });
elements.selectAll.addEventListener("change", () => { for (const issue of state.analysis.issues) if (issue.repairable) issue.selected = elements.selectAll.checked; renderResults(state.analysis, () => updateRepairButton(state.analysis)); });
elements.repair.addEventListener("click", repairSelected);
elements.download.addEventListener("click", () => { if (state.output) downloadBlob(state.output, state.outputName); });
for (const button of [elements.checkAnother, elements.restart, elements.errorRestart]) button.addEventListener("click", restart);

window.addEventListener("beforeunload", () => { state.output = null; });
