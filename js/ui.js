import {paginateIssues, RESULTS_PAGE_SIZE} from "./ifc-batch.js?v=1.0.0-r8";

const byId = id => document.getElementById(id);

const resultsView = {analysis: null, onSelectionChanged: null, fileIndex: "all", page: 1};

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
  selectAll: byId("select-all"),
  fileFilter: byId("file-filter"),
  pageSummary: byId("page-summary"),
  pageNumber: byId("page-number"),
  previousPage: byId("previous-page"),
  nextPage: byId("next-page"),
  repair: byId("repair-button"),
  checkAnother: byId("check-another"),
  completion: byId("completion-card"),
  completionSummary: byId("completion-summary"),
  downloadList: byId("download-list"),
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
  td.textContent = value ?? "-";
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
    option.textContent = `${file.fileName} (${file.issueCount.toLocaleString()} issue${file.issueCount === 1 ? "" : "s"})`;
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
    const selectCell = document.createElement("td");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = issue.selected;
    checkbox.disabled = !issue.repairable;
    checkbox.setAttribute("aria-label", `Apply repair to ${issue.fileName} #${issue.id}`);
    checkbox.addEventListener("change", () => {
      issue.selected = checkbox.checked;
      resultsView.onSelectionChanged();
    });
    selectCell.append(checkbox);
    row.append(selectCell);

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
    td.colSpan = 11;
    elements.body.append(row);
  }

  if (!page.totalItems && !visibleErrors.length) {
    const row = document.createElement("tr");
    const td = cell(row, analysis.unsupportedMessage || "No supported missing geometry references were detected for this file.");
    td.colSpan = 11;
    elements.body.append(row);
  }

  const scope = resultsView.fileIndex === "all"
    ? "across all files"
    : `in ${analysis.files[Number(resultsView.fileIndex)]?.fileName || "this file"}`;
  elements.pageSummary.textContent = `Showing ${page.start.toLocaleString()}–${page.end.toLocaleString()} of ${page.totalItems.toLocaleString()} issues ${scope} · 20 per page`;
  elements.pageNumber.textContent = `Page ${page.currentPage.toLocaleString()} of ${page.totalPages.toLocaleString()}`;
  elements.previousPage.disabled = page.currentPage <= 1;
  elements.nextPage.disabled = page.currentPage >= page.totalPages;
}

export function renderResults(analysis, onSelectionChanged) {
  const changedAnalysis = resultsView.analysis !== analysis;
  resultsView.analysis = analysis;
  resultsView.onSelectionChanged = onSelectionChanged;
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
  elements.review.textContent = analysis.reviewOnly.toLocaleString();
  elements.schema.textContent = analysis.schema;
  const counts = analysis.counts || {};
  elements.signatureSummary.textContent =
    `Files checked: ${analysis.successfulFiles.toLocaleString()} of ${analysis.filesScanned.toLocaleString()} · ` +
    `Body / SweptSolid: ${(counts.bodySweptSolid || 0).toLocaleString()} · ` +
    `Body / Tessellation: ${(counts.bodyTessellation || 0).toLocaleString()} · ` +
    `FootPrint / Curve2D: ${(counts.footprintCurve2D || 0).toLocaleString()}`;
  renderResultsPage();
  updateRepairButton(analysis);
}

export function updateRepairButton(analysis) {
  const count = analysis.issues.filter(issue => issue.selected && issue.repairable).length;
  elements.repair.disabled = count === 0;
  elements.repair.textContent = count ? "Repair all files" : "No safe repairs selected";
  elements.selectAll.checked = count > 0 && count === analysis.repairable;
  elements.selectAll.disabled = analysis.repairable === 0;
}

export function showCompletion(result, outputCount, onDownload) {
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.remove("hidden");
  elements.completionSummary.textContent =
    `${result.successfulChanges.toLocaleString()} of ${result.expectedChanges.toLocaleString()} planned context repair${result.expectedChanges === 1 ? "" : "s"} verified; ` +
    `${result.unexpectedChanges.toLocaleString()} unexpected changes; ` +
    `${result.remainingSupportedMissing.toLocaleString()} supported missing context${result.remainingSupportedMissing === 1 ? "" : "s"} remain. ` +
    `${outputCount.toLocaleString()} repaired IFC file${outputCount === 1 ? "" : "s"} packaged in one ZIP.`;
  elements.downloadList.replaceChildren();
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button primary";
  button.textContent = `Download all files (.zip)`;
  button.addEventListener("click", onDownload);
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
  resultsView.onSelectionChanged = null;
  resultsView.fileIndex = "all";
  resultsView.page = 1;
  elements.input.value = "";
  elements.selectCard.classList.remove("has-file");
  elements.fileSummary.classList.add("hidden");
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.add("hidden");
  elements.error.classList.add("hidden");
  elements.body.replaceChildren();
  elements.downloadList.replaceChildren();
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

