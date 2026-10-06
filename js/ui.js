import {paginateIssues, RESULTS_PAGE_SIZE} from "./ifc-batch.js?v=2.1";

const byId = id => document.getElementById(id);

const resultsView = {analysis: null, fileIndex: "all"};

export const elements = {
  selectCard: byId("select-card"),
  breakdown: byId("issue-breakdown"),
  fileErrors: byId("file-errors"),
  fileFilterRow: byId("file-filter-row"),
  fileFilter: byId("file-filter"),
  shellPanel: byId("shell-panel"),
  shellSummary: byId("shell-summary"),
  shellBody: byId("shell-body"),
  shellPage: byId("shell-page"),
  shellPrevious: byId("shell-previous"),
  shellNext: byId("shell-next"),
  contextPanel: byId("context-panel"),
  contextSummary: byId("context-summary"),
  contextBody: byId("context-body"),
  contextPage: byId("context-page"),
  contextPrevious: byId("context-previous"),
  contextNext: byId("context-next"),
  spacePanel: byId("space-panel"),
  spaceSummary: byId("space-summary"),
  spaceBody: byId("space-body"),
  spacePage: byId("space-page"),
  spacePrevious: byId("space-previous"),
  spaceNext: byId("space-next"),
  reportBar: byId("report-bar"),
  reportSummary: byId("report-summary"),
  reportButton: byId("report-button"),
  completionReportNote: byId("completion-report-note"),
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
  issues: byId("issues-count"),
  repairable: byId("repairable-count"),
  review: byId("review-count"),
  schema: byId("schema-value"),
  schemaMetric: byId("schema-metric"),
  schemaNote: byId("schema-note"),
  spaceMetric: byId("space-metric"),
  spaceCount: byId("space-count"),
  signatureSummary: byId("signature-summary"),
  repairFileSummary: byId("repair-file-summary"),
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

const isShell = issue => issue.issueType === "emptyClosedShell";

// One view per issue table; both follow the shared file filter.
const views = {
  shell: {page: 1, match: isShell},
  context: {page: 1, match: issue => !isShell(issue)},
  space: {page: 1, source: analysis => analysis.spaceIssues},
};

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
      ? `${file.fileName} (${file.blockedSchema ? `blocked: ${file.blockedSchema}, not IFC4` : "file could not be checked"})`
      : `${file.fileName} (${(file.issueCount + file.spaceIssueCount).toLocaleString()} issue${file.issueCount + file.spaceIssueCount === 1 ? "" : "s"})`;
    elements.fileFilter.append(option);
  }
  elements.fileFilter.value = resultsView.fileIndex;
}

// Element name cell; items the tool will not repair carry a visible tag and the reason.
function nameCell(row, issue) {
  const td = cell(row, issue.productName);
  if (!issue.repairable) {
    const tag = document.createElement("span");
    tag.className = "pill review";
    tag.textContent = "NOT REPAIRED";
    td.prepend(tag);
    const reason = document.createElement("small");
    reason.textContent = issue.reason;
    td.append(reason);
  }
}

const classLabel = issue => issue.isType ? `${issue.productType} (type)` : issue.productType;
const viewLabel = issue => issue.signature?.startsWith("footprint|") ? "FootPrint (2D plan)" : "Body (3D model)";

const TABLES = {
  shell: {
    body: () => elements.shellBody, page: () => elements.shellPage,
    previous: () => elements.shellPrevious, next: () => elements.shellNext,
    row: (row, issue) => {
      nameCell(row, issue);
      cell(row, issue.objectType || classLabel(issue));
      cell(row, issue.revitId || "—", "mono strong");
      cell(row, issue.globalId || "—", "mono");
    },
  },
  context: {
    body: () => elements.contextBody, page: () => elements.contextPage,
    previous: () => elements.contextPrevious, next: () => elements.contextNext,
    row: (row, issue) => {
      nameCell(row, issue);
      cell(row, classLabel(issue));
      cell(row, `#${issue.id}`, "mono strong");
      cell(row, viewLabel(issue));
    },
  },
  space: {
    body: () => elements.spaceBody, page: () => elements.spacePage,
    previous: () => elements.spacePrevious, next: () => elements.spaceNext,
    row: (row, space) => {
      cell(row, space.number, "strong");
      cell(row, space.name);
      cell(row, space.level);
      cell(row, space.revitId, "mono strong");
      const why = cell(row, space.reasonLabel);
      why.title = space.reasonDetail;
      const detail = document.createElement("small");
      detail.textContent = `Area ${space.area} · Height ${space.height}`;
      why.append(detail);
      cell(row, space.guid, "mono");
    },
  },
};

function renderTable(key) {
  const analysis = resultsView.analysis;
  if (!analysis) return;
  const view = views[key], table = TABLES[key];
  const items = view.source ? view.source(analysis) : analysis.issues.filter(view.match);
  const page = paginateIssues(items, resultsView.fileIndex, view.page, RESULTS_PAGE_SIZE);
  view.page = page.currentPage;
  table.body().replaceChildren();
  for (const issue of page.items) {
    const row = document.createElement("tr");
    table.row(row, issue);
    table.body().append(row);
  }
  if (!page.totalItems) {
    const row = document.createElement("tr");
    cell(row, "No issues of this kind in the selected file.").colSpan = table.body().closest("table").tHead.rows[0].cells.length;
    table.body().append(row);
  }
  table.page().textContent = `Page ${page.currentPage.toLocaleString()} of ${page.totalPages.toLocaleString()} · ${page.totalItems.toLocaleString()} item${page.totalItems === 1 ? "" : "s"}`;
  table.previous().disabled = page.currentPage <= 1;
  table.next().disabled = page.currentPage >= page.totalPages;
}

function renderBreakdown(analysis) {
  const counts = analysis.counts || {};
  const rows = [
    ["Empty IfcClosedShell", counts.emptyClosedShell || 0, "shell"],
    ["Body context missing", (counts.bodySweptSolid || 0) + (counts.bodyTessellation || 0), ""],
    ["FootPrint context missing", counts.footprintCurve2D || 0, ""],
    ["Area without geometry (report only)", analysis.spaceIssues.length, "shell"],
  ];
  elements.breakdown.replaceChildren(...rows.map(([label, count, className]) => {
    const item = document.createElement("li");
    if (className && count) item.className = className;
    const name = document.createElement("span");
    name.textContent = label;
    const value = document.createElement("b");
    value.textContent = count.toLocaleString();
    item.append(name, value);
    return item;
  }));
}

function panelSummary(issues, repairText) {
  const repairable = issues.filter(issue => issue.repairable).length;
  const review = issues.length - repairable;
  const parts = [`${issues.length.toLocaleString()} item${issues.length === 1 ? "" : "s"}`];
  if (repairable) parts.push(repairText(repairable));
  if (review) parts.push(`${review.toLocaleString()} cannot be repaired automatically`);
  return `${parts.join(" · ")}.`;
}

function renderPanels(analysis, changedAnalysis) {
  const shellIssues = analysis.issues.filter(isShell);
  const contextIssues = analysis.issues.filter(issue => !isShell(issue));
  elements.shellPanel.classList.toggle("hidden", !shellIssues.length);
  elements.contextPanel.classList.toggle("hidden", !contextIssues.length);
  elements.spacePanel.classList.toggle("hidden", !analysis.spaceIssues.length);
  elements.fileFilterRow.classList.toggle("hidden", analysis.files.length < 2 || !(analysis.issues.length || analysis.spaceIssues.length));
  if (changedAnalysis) {
    elements.shellPanel.open = false;
    elements.contextPanel.open = false;
    elements.spacePanel.open = false;
    for (const view of Object.values(views)) view.page = 1;
  }
  elements.shellSummary.textContent = panelSummary(shellIssues,
    count => `${count.toLocaleString()} will have their empty shapes deleted, please check them first`);
  elements.contextSummary.textContent = panelSummary(contextIssues,
    count => `${count.toLocaleString()} will get the missing link (nothing deleted)`);
  const spaceCount = analysis.spaceIssues.length;
  const areas = count => `${count.toLocaleString()} area${count === 1 ? "" : "s"}`;
  elements.spaceSummary.textContent = `${spaceCount.toLocaleString()} of ${analysis.spacesScanned.toLocaleString()} IfcSpace${analysis.spacesScanned === 1 ? "" : "s"} ${spaceCount === 1 ? "has" : "have"} no shape. Report only: fix them in Revit.`;
  elements.reportBar.classList.toggle("hidden", !spaceCount);
  elements.reportSummary.textContent = `${areas(spaceCount)} without geometry, with the reason, the Revit Lookup ID and how to fix each one. The repaired ZIP also includes this report.`;
  elements.fileErrors.classList.toggle("hidden", !analysis.fileErrors.length);
  elements.fileErrors.replaceChildren(...analysis.fileErrors.map(fileError => {
    const item = document.createElement("li");
    item.textContent = `${fileError.fileName}: ${fileError.message}`;
    return item;
  }));
  for (const key of Object.keys(TABLES)) renderTable(key);
}

export function renderResults(analysis) {
  const changedAnalysis = resultsView.analysis !== analysis;
  resultsView.analysis = analysis;
  if (changedAnalysis) {
    resultsView.fileIndex = "all";
    populateFileFilter(analysis);
  }
  elements.progressCard.classList.add("hidden");
  elements.results.classList.remove("hidden");
  elements.completion.classList.add("hidden");
  elements.issues.textContent = (analysis.issues.length + analysis.spaceIssues.length).toLocaleString();
  elements.repairable.textContent = analysis.repairable.toLocaleString();
  // Blocked non-IFC4 files are shown in the red schema box, not counted again here.
  const unreadable = analysis.fileErrors.filter(fileError => !fileError.blocked).length;
  elements.review.textContent = (analysis.reviewOnly + unreadable).toLocaleString();
  elements.spaceMetric.classList.toggle("hidden", !analysis.spaceIssues.length);
  elements.spaceCount.textContent = analysis.spaceIssues.length.toLocaleString();
  elements.schema.textContent = analysis.schema;
  const blocked = analysis.blockedSchemas || [];
  elements.schemaMetric.classList.toggle("blocked", blocked.length > 0);
  elements.schemaNote.classList.toggle("hidden", !blocked.length);
  elements.schemaNote.textContent = blocked.length
    ? `CORENET X does not support ${blocked.join(" or ")}. Only IFC4 files are accepted. Export the model from Revit again as IFC4 with the IFC+SG settings.`
    : "";
  elements.signatureSummary.textContent = analysis.issues.length || analysis.fileErrors.length
    ? `Files checked: ${analysis.successfulFiles.toLocaleString()} of ${analysis.filesScanned.toLocaleString()}.`
    : analysis.spaceIssues.length
      ? "No missing contexts or empty IfcClosedShell geometry were detected, so there is nothing to repair. Some areas have no geometry: download the areas report and fix them in Revit."
      : "No supported missing contexts, empty IfcClosedShell geometry or areas without geometry were detected. There is nothing to repair.";
  const repairFileIndexes = new Set(analysis.issues.filter(issue => issue.repairable).map(issue => issue.fileIndex));
  const cleanFiles = analysis.files.filter(file => !file.error && file.issueCount + file.spaceIssueCount === 0).length;
  const manualOnlyFiles = analysis.files.filter(file => !file.error && file.issueCount + file.spaceIssueCount > 0 &&
    !repairFileIndexes.has(file.fileIndex)).length;
  const fileClauses = [`${repairFileIndexes.size.toLocaleString()} of ${analysis.successfulFiles.toLocaleString()} checked file${analysis.successfulFiles === 1 ? "" : "s"} will be repaired automatically`];
  if (cleanFiles) fileClauses.push(`${cleanFiles.toLocaleString()} need no repair`);
  if (manualOnlyFiles) fileClauses.push(`${manualOnlyFiles.toLocaleString()} need fixes in Revit only`);
  const blockedFiles = analysis.fileErrors.length - unreadable;
  if (blockedFiles) fileClauses.push(`${blockedFiles.toLocaleString()} blocked because ${blockedFiles === 1 ? "it is" : "they are"} not IFC4`);
  if (unreadable) fileClauses.push(`${unreadable.toLocaleString()} could not be checked`);
  elements.repairFileSummary.textContent = `${fileClauses.join(" · ")}.`;
  renderBreakdown(analysis);
  renderPanels(analysis, changedAnalysis);
  updateRepairButton(analysis);
}

export function repairAllowed(analysis) {
  return Boolean(analysis?.issues.some(issue => issue.selected && issue.repairable));
}

export function updateRepairButton(analysis) {
  const count = analysis.issues.filter(issue => issue.selected && issue.repairable).length;
  elements.repair.disabled = !repairAllowed(analysis);
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

export function showCompletion(result, packageInfo, onDownload, onReport = null) {
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.remove("hidden");
  elements.completionSummary.textContent =
    `${result.successfulChanges.toLocaleString()} of ${result.expectedChanges.toLocaleString()} planned repair${result.expectedChanges === 1 ? "" : "s"} verified; ` +
    `${result.unexpectedChanges.toLocaleString()} unexpected changes; ` +
    `${result.remainingSupportedMissing.toLocaleString()} supported issue${result.remainingSupportedMissing === 1 ? "" : "s"} remain. ` +
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
  elements.completionReportNote.classList.toggle("hidden", !onReport);
  if (onReport) {
    const reportButton = document.createElement("button");
    reportButton.type = "button";
    reportButton.className = "button";
    reportButton.textContent = "Download areas report only";
    reportButton.addEventListener("click", onReport);
    elements.downloadList.append(reportButton);
  }
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
  elements.input.value = "";
  elements.selectCard.classList.remove("hidden");
  elements.selectCard.classList.remove("has-file");
  elements.fileSummary.classList.add("hidden");
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.add("hidden");
  elements.error.classList.add("hidden");
  elements.downloadList.replaceChildren();
  elements.downloadProgressPanel.classList.add("hidden");
  elements.shellPanel.classList.add("hidden");
  elements.contextPanel.classList.add("hidden");
  elements.spacePanel.classList.add("hidden");
  elements.reportBar.classList.add("hidden");
  elements.spaceMetric.classList.add("hidden");
  elements.schemaMetric.classList.remove("blocked");
  elements.schemaNote.classList.add("hidden");
  elements.shellPanel.open = false;
  elements.contextPanel.open = false;
  elements.spacePanel.open = false;
  elements.spaceBody.replaceChildren();
  elements.shellBody.replaceChildren();
  elements.contextBody.replaceChildren();
  elements.breakdown.replaceChildren();
  elements.fileErrors.replaceChildren();
  setStep(1);
}

for (const key of Object.keys(TABLES)) {
  TABLES[key].previous().addEventListener("click", () => { views[key].page -= 1; renderTable(key); });
  TABLES[key].next().addEventListener("click", () => { views[key].page += 1; renderTable(key); });
}
elements.fileFilter.addEventListener("change", () => {
  resultsView.fileIndex = elements.fileFilter.value;
  for (const key of Object.keys(TABLES)) {
    views[key].page = 1;
    renderTable(key);
  }
});
