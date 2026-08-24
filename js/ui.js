const byId = id => document.getElementById(id);

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
  selectAll: byId("select-all"),
  repair: byId("repair-button"),
  checkAnother: byId("check-another"),
  completion: byId("completion-card"),
  completionSummary: byId("completion-summary"),
  download: byId("download-button"),
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

export function showFile(file) {
  elements.selectCard.classList.add("has-file");
  elements.fileSummary.classList.remove("hidden");
  elements.fileDetails.textContent = `${file.name} | ${formatBytes(file.size)} | Ready for local processing`;
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

export function renderResults(analysis, onSelectionChanged) {
  elements.progressCard.classList.add("hidden");
  elements.results.classList.remove("hidden");
  elements.completion.classList.add("hidden");
  elements.issues.textContent = analysis.issues.length.toLocaleString();
  elements.repairable.textContent = analysis.repairable.toLocaleString();
  elements.review.textContent = analysis.reviewOnly.toLocaleString();
  elements.schema.textContent = analysis.schema;
  elements.body.replaceChildren();

  for (const issue of analysis.issues) {
    const row = document.createElement("tr");
    const selectCell = document.createElement("td");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = issue.selected;
    checkbox.disabled = !issue.repairable;
    checkbox.setAttribute("aria-label", `Apply repair to #${issue.id}`);
    checkbox.addEventListener("change", () => {
      issue.selected = checkbox.checked;
      onSelectionChanged();
    });
    selectCell.append(checkbox);
    row.append(selectCell);

    const outcome = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = `pill ${issue.repairable ? "safe" : "review"}`;
    pill.textContent = issue.repairable ? "READY TO REPAIR" : "REPORT ONLY";
    outcome.append(pill);
    row.append(outcome);
    cell(row, `#${issue.id}`);
    cell(row, issue.productType);
    cell(row, issue.productName);
    cell(row, `${issue.identifier} / ${issue.representationType}`);
    cell(row, issue.details);
    elements.body.append(row);
  }

  if (!analysis.issues.length) {
    const row = document.createElement("tr");
    const td = cell(row, analysis.unsupportedMessage || "No supported missing geometry references were detected.");
    td.colSpan = 7;
    elements.body.append(row);
  }
  updateRepairButton(analysis);
}

export function updateRepairButton(analysis) {
  const count = analysis.issues.filter(issue => issue.selected && issue.repairable).length;
  elements.repair.disabled = count === 0;
  elements.repair.textContent = count
    ? `Repair ${count.toLocaleString()} selected issue${count === 1 ? "" : "s"}`
    : "No safe repairs selected";
  elements.selectAll.checked = count > 0 && count === analysis.repairable;
  elements.selectAll.disabled = analysis.repairable === 0;
}

export function showCompletion(result, filename) {
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.remove("hidden");
  elements.completionSummary.textContent = `${result.repaired.toLocaleString()} geometry reference${result.repaired === 1 ? "" : "s"} repaired and verified. ${filename} is ready to download.`;
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
  elements.input.value = "";
  elements.selectCard.classList.remove("has-file");
  elements.fileSummary.classList.add("hidden");
  elements.progressCard.classList.add("hidden");
  elements.results.classList.add("hidden");
  elements.completion.classList.add("hidden");
  elements.error.classList.add("hidden");
  elements.body.replaceChildren();
  setStep(1);
}

