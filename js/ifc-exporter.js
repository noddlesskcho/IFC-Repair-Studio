export function repairedFileName(name) {
  return name.replace(/\.ifc$/i, "") + "_repaired.ifc";
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.style.display = "none";
  document.body.append(anchor); anchor.click(); anchor.remove();
  // Keep the URL alive while a slow Save dialog is still open.
  setTimeout(() => URL.revokeObjectURL(url), 300_000);
}
