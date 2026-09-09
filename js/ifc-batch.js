const emptyCounts = () => ({bodySweptSolid: 0, bodyTessellation: 0, footprintCurve2D: 0});

export function combineAnalyses(entries) {
  const counts = emptyCounts();
  const issues = [];
  const fileErrors = [];
  const schemas = new Set();
  let representationsScanned = 0;
  let productsScanned = 0;

  entries.forEach((entry, fileIndex) => {
    if (entry.error) {
      fileErrors.push({fileIndex, fileName: entry.file.name, message: entry.error.message || String(entry.error)});
      return;
    }
    const analysis = entry.analysis;
    schemas.add(analysis.schema);
    representationsScanned += analysis.representationsScanned || 0;
    productsScanned += analysis.productsScanned || 0;
    for (const key of Object.keys(counts)) counts[key] += analysis.counts?.[key] || 0;
    for (const issue of analysis.issues) issues.push({...issue, fileIndex, fileName: entry.file.name});
  });

  const schema = schemas.size === 1 ? [...schemas][0] : schemas.size ? [...schemas].join(" / ") : "—";
  return {
    schema,
    filesScanned: entries.length,
    successfulFiles: entries.length - fileErrors.length,
    fileErrors,
    issues,
    counts,
    representationsScanned,
    productsScanned,
    repairable: issues.filter(issue => issue.repairable).length,
    reviewOnly: issues.filter(issue => !issue.repairable).length,
    unsupportedMessage: issues.length || fileErrors.length ? null : "No supported missing geometry references were detected.",
  };
}

export function selectedIssuesForFile(analysis, fileIndex) {
  return analysis.issues.filter(issue => issue.fileIndex === fileIndex && issue.selected && issue.repairable);
}
