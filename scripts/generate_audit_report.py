from __future__ import annotations

import sys
from pathlib import Path

from ifc_context_repair.repair import analyse


report = analyse(Path(sys.argv[1]), repair_mode="audit")
print(report.report_paths)
print(report.summary_counts)
print(report.classification_counts)
