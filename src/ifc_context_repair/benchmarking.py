from __future__ import annotations

import csv
import gc
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Iterable

from .feature_flags import RepairFeatureFlags
from .repair import analyse


@dataclass(slots=True)
class BenchmarkResult:
    test_name: str
    input_file: str
    input_size_bytes: int
    configuration: str
    run_number: int
    total_seconds: float
    scan_seconds: float
    semantic_load_seconds: float
    index_seconds: float
    detection_seconds: float
    planning_seconds: float
    patch_write_seconds: float
    verification_seconds: float
    report_seconds: float
    peak_rss_bytes: int | None
    temp_disk_bytes: int
    targets_detected: int
    targets_repaired: int
    remaining_targets: int
    unexpected_changes: int


CONFIGURATIONS = {
    "Baseline A - broad": RepairFeatureFlags(True, True, True),
    "Baseline B - indirect detected only": RepairFeatureFlags(True, True, True),
    "Optimised Version 1": RepairFeatureFlags.version_1(),
}


def _rss() -> int | None:
    try:
        import psutil  # type: ignore

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def benchmark_scan(
    path: Path,
    *,
    test_name: str,
    configuration: str,
    run_number: int,
) -> BenchmarkResult:
    flags = CONFIGURATIONS[configuration]
    before_rss = _rss()
    started = time.perf_counter()
    report = analyse(
        path,
        validate=False,
        quick=True,
        repair_mode="production",
        feature_flags=flags,
        developer_mode=flags.indirect_enabled,
    )
    total = time.perf_counter() - started
    durations = report.durations
    after_rss = _rss()
    direct = [
        item for item in report.diagnoses
        if item.classification.value == "DIRECT_PRODUCT"
    ]
    result = BenchmarkResult(
        test_name=test_name,
        input_file=str(path.resolve()),
        input_size_bytes=path.stat().st_size,
        configuration=configuration,
        run_number=run_number,
        total_seconds=total,
        scan_seconds=durations.get("step_prescan", 0.0),
        semantic_load_seconds=durations.get("ifc_opening", 0.0),
        index_seconds=sum(
            durations.get(key, 0.0)
            for key in ("context_index", "indirect_index_build")
        ),
        detection_seconds=sum(
            durations.get(key, 0.0)
            for key in (
                "collect_target_elements",
                "collect_shape_representations",
                "indirect_classification",
                "context_resolution",
            )
        ),
        planning_seconds=durations.get("build_patch_plan", 0.0),
        patch_write_seconds=durations.get("apply_patches", 0.0),
        verification_seconds=sum(
            durations.get(key, 0.0)
            for key in ("targeted_verification", "unexpected_change_audit")
        ),
        report_seconds=sum(
            value for key, value in durations.items() if "report" in key
        ),
        peak_rss_bytes=(
            max(value for value in (before_rss, after_rss) if value is not None)
            if before_rss is not None or after_rss is not None else None
        ),
        temp_disk_bytes=0,
        targets_detected=len(direct),
        targets_repaired=0,
        remaining_targets=len(direct),
        unexpected_changes=0,
    )
    # IfcOpenShell models may participate in wrapper reference cycles. Release
    # each measured run before starting the next so benchmark iterations do not
    # measure accumulated models or force the machine into paging.
    del report
    gc.collect()
    return result


def _groups(results: Iterable[BenchmarkResult]) -> dict[tuple[str, str], list[BenchmarkResult]]:
    grouped: dict[tuple[str, str], list[BenchmarkResult]] = {}
    for result in results:
        grouped.setdefault((result.test_name, result.configuration), []).append(result)
    return grouped


def export_results(results: list[BenchmarkResult], output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "benchmark_results.json"
    csv_path = output_dir / "benchmark_results.csv"
    html_path = output_dir / "benchmark_summary.html"
    rows = [asdict(item) for item in results]
    json_path.write_text(
        json.dumps(
            {
                "environment": {
                    "platform": platform.platform(),
                    "processor": platform.processor(),
                    "python": sys.version,
                    "storage_note": "Recorded by operator; local/synchronised path shown in input_file",
                    "warm_up_excluded": True,
                },
                "results": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")
    summaries = []
    for (test_name, configuration), values in sorted(_groups(results).items()):
        totals = [value.total_seconds for value in values]
        summaries.append({
            "test_name": test_name,
            "configuration": configuration,
            "runs": len(values),
            "median": statistics.median(totals),
            "minimum": min(totals),
            "maximum": max(totals),
            "scan": statistics.median(value.scan_seconds for value in values),
            "index": statistics.median(value.index_seconds for value in values),
            "detection": statistics.median(value.detection_seconds for value in values),
            "peak_rss": max(
                (value.peak_rss_bytes or 0 for value in values), default=0
            ),
        })
    table_rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in (
            row["test_name"], row["configuration"], row["runs"],
            f"{row['scan']:.3f}", f"{row['index']:.3f}",
            f"{row['detection']:.3f}", f"{row['median']:.3f}",
            f"{row['minimum']:.3f} - {row['maximum']:.3f}",
            row["peak_rss"],
        )) + "</tr>"
        for row in summaries
    )
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Version 1 benchmark</title>"
        "<style>body{font:14px Segoe UI;margin:32px;color:#172033}table{border-collapse:collapse}"
        "th,td{padding:8px;border:1px solid #ccd5e1;text-align:right}th:first-child,td:first-child,"
        "th:nth-child(2),td:nth-child(2){text-align:left}</style>"
        "<h1>IFC+SG Repair Assistant - Version 1 Benchmark</h1>"
        "<p>Warm-up runs are excluded. Values are measured medians; min-max is shown.</p>"
        "<table><thead><tr><th>File</th><th>Configuration</th><th>Runs</th>"
        "<th>Pre-scan (s)</th><th>Index (s)</th><th>Detection (s)</th>"
        "<th>Total median (s)</th><th>Total min-max (s)</th><th>Peak RSS (bytes)</th>"
        f"</tr></thead><tbody>{table_rows}</tbody></table>",
        encoding="utf-8",
    )
    return json_path, csv_path, html_path
