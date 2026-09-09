import {analyzeIfc} from "./ifc-analyzer.js?v=1.0.0-r11";
import {combineAnalyses, selectedIssuesForFile} from "./ifc-batch.js?v=1.0.0-r11";
import {downloadBlob, repairedFileName} from "./ifc-exporter.js?v=1.0.0-r11";
import {applyRepairs, verifyRepairedModel, verifyRepairs} from "./ifc-fixer.js?v=1.0.0-r11";
import {loadIfc} from "./ifc-loader.js?v=1.0.0-r11";
import {createRepairedZip, repairedArchiveName} from "./zip-exporter.js?v=1.0.0-r11";
import {
  elements, renderResults, resetUi, setStep, showCompletion, showError, showFiles,
  updateProgress, updateRepairButton,
} from "./ui.js?v=1.0.0-r11";

const state = {entries: [], analysis: null, outputs: [], archive: null, busy: false};

function setBusy(value) {
  state.busy = value;
  elements.choose.disabled = value;
  elements.changeFile.disabled = value;
  elements.repair.disabled = value || !state.analysis?.repairable;
}

function progressForFile(index, total, fileName, activity = "") {
  return progress => updateProgress({
    ...progress,
    stage: `${activity}${index + 1}/${total}: ${fileName} — ${progress.stage}`,
  });
}

async function processFiles(fileList) {
  if (state.busy) return;
  const files = [...fileList];
  if (!files.length) return;
  resetUi();
  state.entries = [];
  state.analysis = null;
  state.outputs = [];
  state.archive = null;
  showFiles(files);
  setStep(2);
  setBusy(true);
  try {
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      const reportProgress = progressForFile(index, files.length, file.name, "Checking ");
      try {
        const model = await loadIfc(file, reportProgress);
        const analysis = await analyzeIfc(model, reportProgress);
        state.entries.push({file, analysis, error: null});
      } catch (error) {
        state.entries.push({file, analysis: null, error});
      }
    }
    state.analysis = combineAnalyses(state.entries);
    renderResults(state.analysis);
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
    if (state.analysis) updateRepairButton(state.analysis);
  }
}

async function repairSelected() {
  if (state.busy || !state.analysis) return;
  setBusy(true);
  const selectedCount = state.analysis.issues.filter(issue => issue.selected && issue.repairable).length;
  updateProgress({stage: "Preparing automatic repairs", current: 0, total: selectedCount});
  window.scrollTo({top: 0, behavior: "smooth"});
  state.outputs = [];
  state.archive = null;
  const summary = {
    expectedChanges: 0,
    successfulChanges: 0,
    unexpectedChanges: 0,
    remainingSupportedMissing: 0,
  };
  try {
    for (let index = 0; index < state.entries.length; index += 1) {
      const entry = state.entries[index];
      if (entry.error) continue;
      const selected = selectedIssuesForFile(state.analysis, index);
      if (!selected.length) continue;
      const reportProgress = progressForFile(index, state.entries.length, entry.file.name, "Repairing ");
      const {output, repairs} = await applyRepairs(entry.file, selected, reportProgress);
      const byteResult = await verifyRepairs(entry.file, output, repairs, reportProgress);
      const outputName = repairedFileName(entry.file.name);
      updateProgress({stage: `Rechecking ${index + 1}/${state.entries.length}: ${outputName}`, current: 0, total: output.size, unit: "bytes"});
      const outputModel = await loadIfc(output, reportProgress, outputName);
      const semanticResult = verifyRepairedModel(outputModel, repairs);
      const postAnalysis = await analyzeIfc(outputModel, reportProgress);
      const result = {
        ...byteResult,
        ...semanticResult,
        remainingSupportedMissing: postAnalysis.issues.length,
      };
      summary.expectedChanges += result.expectedChanges;
      summary.successfulChanges += result.successfulChanges;
      summary.unexpectedChanges += result.unexpectedChanges;
      summary.remainingSupportedMissing += result.remainingSupportedMissing;
      state.outputs.push({blob: output, name: outputName, result});
    }
    const outputCount = state.outputs.length;
    const cleanFiles = state.entries.filter(entry => !entry.error && entry.analysis.issues.length === 0).length;
    const manualOnlyFiles = state.entries.filter(entry => !entry.error && entry.analysis.issues.length > 0 &&
      !entry.analysis.issues.some(issue => issue.repairable)).length;
    showCompletion(summary, {
      outputCount,
      cleanFiles,
      manualOnlyFiles,
      fileErrors: state.analysis.fileErrors.length,
    }, async reportProgress => {
      if (!state.archive) state.archive = await createRepairedZip(state.outputs, reportProgress);
      else reportProgress({stage: "ZIP ready", current: state.archive.size, total: state.archive.size, unit: "bytes"});
      downloadBlob(state.archive, repairedArchiveName());
    });
  } catch (error) {
    state.outputs = [];
    state.archive = null;
    showError(error);
  } finally {
    setBusy(false);
  }
}

function restart() {
  state.entries = [];
  state.analysis = null;
  state.outputs = [];
  state.archive = null;
  resetUi();
}

elements.choose.addEventListener("click", () => elements.input.click());
elements.changeFile.addEventListener("click", () => elements.input.click());
elements.drop.addEventListener("click", () => elements.input.click());
elements.drop.addEventListener("keydown", event => {
  if (["Enter", " "].includes(event.key)) {
    event.preventDefault();
    elements.input.click();
  }
});
elements.input.addEventListener("change", () => processFiles(elements.input.files));
for (const name of ["dragenter", "dragover"]) {
  elements.drop.addEventListener(name, event => {
    event.preventDefault();
    elements.drop.classList.add("drag");
  });
}
for (const name of ["dragleave", "drop"]) {
  elements.drop.addEventListener(name, event => {
    event.preventDefault();
    elements.drop.classList.remove("drag");
  });
}
elements.drop.addEventListener("drop", event => processFiles(event.dataTransfer.files));
elements.repair.addEventListener("click", repairSelected);
for (const button of [elements.checkAnother, elements.restart, elements.errorRestart]) {
  button.addEventListener("click", restart);
}

window.addEventListener("beforeunload", () => {
  state.outputs = [];
  state.archive = null;
});
