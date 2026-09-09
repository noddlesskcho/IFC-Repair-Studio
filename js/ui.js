import {paginateIssues, RESULTS_PAGE_SIZE} from "./ifc-batch.js?v=1.0.0-r11";

const byId = id => document.getElementById(id);

const resultsView = {analysis: null, fileIndex: "all", page: 1};

export const elements = {
  selectCard: byId("select-card"),
  input: byId("file-input"),
  choose: byId("choose-button"),
  changeFile: byId("change-file-button"),
  drop: byId("drop-zone"),
  fileSummary: byId("file-summary"),
  fileDetails: byId("file-details"),
  progressCard: byId("progress-card"),
  progress: byId("progress"),
  progressTitle: byId("progress-title"),
  progressPercent: byId("progress-percent"),
  progressDetail: byId("progress-detail"),
  results: byId("results-section"),
  body: byId("results-body"),
  issues: byId("issues-count"),
  repairable: byId("repairable-count"),
  review: byId("review-count"),
  schema: byId("schema-value"),
  signatureSummary: byId("signature-summary"),
  repairFileSummary: byId("repair-file-summary"),
  allRepairableMessage: byId("all-repairable-message"),
  reviewDetails: byId("review-details"),
  detailsSummary: byId("details-summary"),
  fileFilter: byId("file-filter"),
  pageSummary: byId("page-summary"),
  pageNumber: byId("page-number"),
  previousPage: byId("previous-page"),
  nextPage: byId("next-page"),
  repair: byId("repair-button"),
  checkAnother: byId("check-another"),
  completion: byId("completion-card"),
  completionSummary: byId("completion-summary"),
  completionPackageSummary: byId("completion-package-summary"),
  downloadList: byId("download-list"),
  downloadProgressPanel: byId("download-progress-panel"),
  downloadProgress: byId("download-progress"),
  downloadStatus: byId("download-status"),
  downloadPercent: byId("download-percent"),
  downloadDetail: byId("download-detail"),
  restart: byId("restart-button"),
  error: byId("error-card"),
  errorMessage: byId("error-message"),
  errorRestart: byId("error-restart"),
};

export function formatBytes(value) {
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

export function setStep(step) {
  document.querySelectorAll(".workflow span").forEach(node => {
    const value = Number(node.dataset.step);
    node.classList.toggle("active", value === step);
    node.classList.toggle("done", value < step);
  });
}

export function showFiles(files) {
  elements.selectCard.classList.add("has-file");
  elements.fileSummary.classList.remove("hidden");
  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  elements.fileDetails.textContent = files.length === 1
    ? `${files[0].name} | ${formatBytes(totalSize)} | Ready for local processing`
    : `${files.length.toLocaleString()} IFC files | ${formatBytes(totalSize)} total | Ready for sequential local processing`;
}

export function updateProgress({stage, current = 0, total = 0, unit = "items"}) {
  elements.progressCard.classList.remove("hidden");
  const percent = total ? Math.min(100, Math.round(current * 100 / total)) : 0;
  elements.progress.value = percent;
  elements.progressPercent.textContent = `${percent}%`;
  elements.progressTitle.textContent = stage;
  elements.progressDetail.textContent = total
    ? unit === "bytes"
      ? `${formatBytes(current)} processed of ${formatBytes(total)}`
      : `${current.toLocaleString()} of ${total.toLocaleString()} items`
    : "Working locally in this browser...";
}

function cell(row, value, className = "") {
  const td = document.createElement("td");
  const content = document.createElement("span");
  content.className = "cell-text";
  content.textContent = value ?? "-";
  content.title = value ?? "-";
  td.append(content);
  if (className) td.className = className;
  row.append(td);
  return td;
}

function populateFileFilter(analysis) {
  elements.fileFilter.replaceChildren();
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = `All files (${analysis.files.length.toLocaleString()})`;
  elements.fileFilter.append(all);
  for (const file of analysis.files) {
    const option = document.createElement("option");
    option.value = String(file.fileIndex);
    option.textContent = file.error
      ? `${file.fileName} (file could not be checked)`
      : `${file.fileName} (${file.issueCount.toLocaleString()} issue${file.issueCount === 1 ? "" : "s"})`;
    elements.fileFilter.append(option);
  }
  elements.fileFilter.value = resultsView.fileIndex;
}

function renderResultsPage() {
  const analysis = resultsView.analysis;
  if (!analysis) return;
  const page = paginateIssues(analysis.issues, resultsView.fileIndex, resultsView.page, RESULTS_PAGE_SIZE);
  resultsView.page = page.currentPage;
  elements.body.replaceChildren();

  for (const issue of page.items) {
    const row = document.createElement("tr");
    const outcome = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = `pill ${issue.repairable ? "safe" : "review"}`;
    pill.textContent = issue.status.toUpperCase();
    outcome.append(pill);
    row.append(outcome);
    cell(row, issue.fileName);
    cell(row, `#${issue.id}`);
    cell(row, issue.identifier);
    cell(row, issue.representationType);
    cell(row, issue.currentContext);
    cell(row, issue.proposedContext);
    cell(row, issue.candidateContextId ? `#${issue.candidateContextId}` : "—");
    cell(row, issue.referencedBy.join(", "));
    cell(row, issue.reason);
    elements.body.append(row);
  }

  const visibleErrors = analysis.fileErrors.filter(error =>
    resultsView.fileIndex === "all" || error.fileIndex === Number(resultsView.fileIndex));
  for (const fileError of visibleErrors) {
    const row = document.createElement("tr");
    const td = cell(row, `${fileError.fileName}: ${fileError.message}`, "file-error");
    td.colSpan = 10;
    elements.body.append(row);
  }

  if (!page.totalItems && !visibleErrors.length) {
    const row = document.createElement("tr");
    const td = cell(row, analysis.unsupportedMessage || "No supported missing geometry references were detected for this file.");
    td.colSpan = 10;
    elements.body.append(row);
  }

  const scope = resultsView.fileIndex === "all"
    ? "across all files"
    : `in ${analysis.files[Number(resultsView.fileIndex)]?.fileName || "this file"}`;
  const errorSummary = visibleErrors.length
    ? ` · ${visibleErrors.length.toLocaleString()} file${visibleErrors.length === 1 ? "" : "s"} could not be checked`
    : "";
  elements.pageSummary.textContent = `Showing ${page.start.toLocaleString()}–${page.end.toLocaleString()} of ${page.totalItems.toLocaleString()} issues ${scope} · 20 per page${errorSummary}`;
  elements.pageNumber.textContent = `Page ${page.currentPage.toLocaleString()} of ${page.totalPages.toLocaleString()}`;
  elements.previousPage.disabled = page.currentPage <= 1;
  elements.nextPage.disabled = page.currentPage >= page.totalPages;
}

export function renderResults(analysis) {
  const changedAnalysis = resultsView.analysis !== analysis;
  resultsView.analysis = analysis;
  if (changedAnalysis) {
    resultsView.fileIndex = "all";
    resultsView.page = 1;
    populateFileFilter(analysis);
  }
  elements.progressCard.classList.add("hidden");
  elements.results.classList.remove("hidden");
  elements.completion.classList.add("hidden");
  elements.issues.textContent = analysis.issues.length.toLocaleString();
  elements.repairable.textContent = analysis.repairable.toLocaleString();
  elements.review.textContent = (analysis.reviewOnly + analysis.fileErrors.length).toLocaleString();
  elements.schema.textContent = analysis.schema;
  const counts = analysis.counts || {};
  elements.signatureSummary.textContent =
    `Files checked: ${analysis.successfulFiles.toLocaleString()} of ${analysis.filesScanned.toLocaleString()} · ` +
    `Body / SweptSolid: ${(counts.bodySweptSolid || 0).toLocaleString()} · ` +
    `Body / Tessellation: ${(counts.bodyTessellation || 0).toLocaleString()} · ` +
    `FootPrint / Curve2D: ${(counts.footprintCurve2D || 0).toLocaleString()}`;
  const repairFileIndexes = new Set(analysis.issues.filter(issue => issue.repairable).map(issue => issue.fileIndex));
  const cleanFiles = analysis.files.filter(file => !file.error && file.issueCount === 0).length;
  const manualOnlyFiles = analysis.files.filter(file => !file.error && file.issueCount > 0 &&
    !repairFileIndexes.has(file.fileIndex)).length;
  const fileClauses = [`${repairFileIndexes.size.toLocaleString()} of ${analysis.successfulFiles.toLocaleString()} checked file${analysis.successfulFiles === 1 ? "" : "s"} will be repaired automatically`];
  if (cleanFiles) fileClauses.push(`${cleanFiles.toLocaleString()} need no repair`);
  if (manualOnlyFiles) fileClauses.push(`${manualOnlyFiles.toLocaleString()} require manual review only`);
  if (analysis.fileErrors.length) fileClauses.push(`${analysis.fileErrors.length.toLocaleString()} could not be checked`);
  elements.repairFileSummary.textContent = `${fileClauses.join(" · ")}.`;

  const hasDetails = analysis.issues.length > 0 || analysis.fileErrors.length > 0;
  elements.reviewDetails.classList.toggle("hidden", !hasDetails);
  if (changedAnalysis) elements.reviewDetails.open = false;
  elements.detailsSummary.textContent = `View repair details (${analysis.issues.length.toLocaleString()} issue${analysis.issues.length === 1 ? "" : "s"})`;
  elements.allRepairableMessage.classList.remove("hidden");
  elements.allRepairableMessage.textContent = analysis.repairable
    ? `${analysis.repairable.toLocaleString()} supported issue${analysis.repairable === 1 ? " is" : "s are"} ready for automatic repair${analysis.reviewOnly ? `; ${analysis.reviewOnly.toLocaleString()} require manual review` : ""}.`
    : analysis.reviewOnly
      ? `${analysis.reviewOnly.toLocaleString()} supported issue${analysis.reviewOnly === 1 ? " requires" : "s require"} manual review; none can be repaired automatically.`
      : "No supported missing contexts were detected. There is nothing to repair.";
  if (hasDetails) renderResultsPage();
  updateRepairButton(analysis);
}

export function updateRepairButton(analysis) {
  const count = analysis.issues.filter(issue => issue.selected && issue.repairable).length;
  elements.repair.disabled = count === 0;
  elements.repair.textContent = count ? "Repair all files" : "No safe repairs selected";
}

function updateDownloadProgress({stage, current = 0, total = 0, unit = "bytes", percent: suppliedPercent, detail}) {
  elements.downloadProgressPanel.classList.remove("hidden");
  const percent = suppliedPercent ?? (total ? Math.min(100, Math.round(current * 100 / total)) : 0);
  elements.downloadProgress.value = percent;
  elements.downloadPercent.textContent = `${percent}%`;
  elements.downloadStatus.textContent = stage;
  elements.downloadDetail.textContent = detail ?? (total && unit === "bytes"
    ? `${formatBytes(current)} packaged of ${formatBytes(total)}`
    : "Packaging the repaired IFC files locally in this browser.");
}

async function animateDownloadHandoff(bytes = 0) {
  const megabytes = bytes / (1024 * 1024);
  const duration = Math.min(10_000, Math.max(3_000, Math.round(megabytes / 80 * 1_000)));
  const interval = duration / 4;
  for (let percent = 96; percent <= 99; percent += 1) {
    await new Promise(resolve => setTimeout(resolve, interval));
    updateDownloadProgress({
      stage: "Preparing browser download...",
      percent,
      detail: "The ZIP is ready. Your browser is preparing the download or Save dialog.",
    });
  }
}

export function showCompletion(result, packageInfo, onDownload) {
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.remove("hidden");
  elements.completionSummary.textContent =
    `${result.successfulChanges.toLocaleString()} of ${result.expectedChanges.toLocaleString()} planned context repair${result.expectedChanges === 1 ? "" : "s"} verified; ` +
    `${result.unexpectedChanges.toLocaleString()} unexpected changes; ` +
    `${result.remainingSupportedMissing.toLocaleString()} supported missing context${result.remainingSupportedMissing === 1 ? "" : "s"} remain. ` +
    `${packageInfo.outputCount.toLocaleString()} repaired IFC file${packageInfo.outputCount === 1 ? " is" : "s are"} ready to package in one ZIP.`;
  const packageClauses = [`${packageInfo.outputCount.toLocaleString()} file${packageInfo.outputCount === 1 ? "" : "s"} with verified repairs will be included`];
  if (packageInfo.cleanFiles) packageClauses.push(`${packageInfo.cleanFiles.toLocaleString()} file${packageInfo.cleanFiles === 1 ? "" : "s"} needed no repair and will not be included`);
  if (packageInfo.manualOnlyFiles) packageClauses.push(`${packageInfo.manualOnlyFiles.toLocaleString()} manual-review file${packageInfo.manualOnlyFiles === 1 ? "" : "s"} will not be included`);
  if (packageInfo.fileErrors) packageClauses.push(`${packageInfo.fileErrors.toLocaleString()} unreadable file${packageInfo.fileErrors === 1 ? "" : "s"} will not be included`);
  elements.completionPackageSummary.textContent = `${packageClauses.join(" · ")}.`;
  elements.selectCard.classList.add("hidden");
  elements.downloadList.replaceChildren();
  elements.downloadProgressPanel.classList.add("hidden");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button primary";
  button.textContent = `Download all files (.zip)`;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Preparing ZIP...";
    updateDownloadProgress({
      stage: "Starting ZIP package...",
      percent: 0,
      detail: "Packaging the repaired IFC files locally in this browser.",
    });
    try {
      await new Promise(resolve => requestAnimationFrame(() => resolve()));
      const downloadResult = await onDownload(progress => {
        const packagingPercent = progress.total
          ? Math.min(95, Math.round(progress.current * 95 / progress.total))
          : 0;
        updateDownloadProgress({...progress, percent: packagingPercent});
      });
      updateDownloadProgress({
        stage: "Preparing browser download...",
        percent: 95,
        detail: "The ZIP is ready. Your browser is preparing the download or Save dialog.",
      });
      await animateDownloadHandoff(downloadResult?.bytes);
      elements.downloadProgress.value = 100;
      elements.downloadPercent.textContent = "100%";
      elements.downloadStatus.textContent = "Download started";
      elements.downloadDetail.textContent = "The ZIP has been passed to your browser's download manager.";
      button.textContent = "Download ZIP again";
    } catch (error) {
      elements.downloadStatus.textContent = "Unable to prepare the ZIP";
      elements.downloadDetail.textContent = error instanceof Error ? error.message : String(error);
      button.textContent = "Try ZIP download again";
    } finally {
      button.disabled = false;
    }
  });
  elements.downloadList.append(button);
  setStep(3);
}

export function showError(error) {
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.add("hidden");
  elements.error.classList.remove("hidden");
  elements.errorMessage.textContent = error instanceof Error ? error.message : String(error);
}

export function resetUi() {
  resultsView.analysis = null;
  resultsView.fileIndex = "all";
  resultsView.page = 1;
  elements.input.value = "";
  elements.selectCard.classList.remove("hidden");
  elements.selectCard.classList.remove("has-file");
  elements.fileSummary.classList.add("hidden");
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.add("hidden");
  elements.error.classList.add("hidden");
  elements.body.replaceChildren();
  elements.downloadList.replaceChildren();
  elements.downloadProgressPanel.classList.add("hidden");
  setStep(1);
}

elements.fileFilter.addEventListener("change", () => {
  resultsView.fileIndex = elements.fileFilter.value;
  resultsView.page = 1;
  renderResultsPage();
});
elements.previousPage.addEventListener("click", () => {
  resultsView.page -= 1;
  renderResultsPage();
});
elements.nextPage.addEventListener("click", () => {
  resultsView.page += 1;
  renderResultsPage();
});

