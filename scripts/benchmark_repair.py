from __future__ import annotations

import argparse
import ctypes
import dataclasses
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from ifc_context_repair.config import RepairConfig
from ifc_context_repair.repair import repair_file


class _MemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def _memory() -> tuple[int, int, int]:
    if os.name != "nt":
        return 0, 0, 0
    counters = _MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_MemoryCounters), ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        return 0, 0, 0
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize), int(counters.PrivateUsage)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--reports", action="store_true")
    parser.add_argument(
        "--mode", choices=("safe", "advanced"), default="safe"
    )
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    samples: list[tuple[int, int, int]] = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(0.05):
            samples.append(_memory())

    before = _memory()
    monitor = threading.Thread(target=sample, name="memory-sampler", daemon=True)
    monitor.start()
    with tempfile.TemporaryDirectory(prefix="ifc-repair-benchmark-") as folder:
        output = Path(folder) / f"{args.input.stem}_repaired.ifc"
        started = time.perf_counter()
        config_values = {
            "source": args.input,
            "output": output,
            "generate_report": args.reports,
            "repair_mode": args.mode,
        }
        if "minimum_confidence" in {item.name for item in dataclasses.fields(RepairConfig)}:
            config_values["minimum_confidence"] = 0.70
        report = repair_file(RepairConfig(**config_values))
        total = time.perf_counter() - started
        output_size = output.stat().st_size
    stop.set()
    monitor.join(timeout=1)
    after = _memory()
    peaks = samples + [before, after]
    result = {
        "input": str(args.input.resolve()),
        "input_size": args.input.stat().st_size,
        "output_size": output_size,
        "total_seconds": total,
        "working_set_before": before[0],
        "working_set_after": after[0],
        "peak_working_set": max((item[1] for item in peaks), default=0),
        "peak_private_bytes": max((item[2] for item in peaks), default=0),
        "durations": report.durations,
        "counts": report.summary_counts,
        "verification": report.targeted_verification,
        "change_audit": getattr(report, "change_audit", {}),
        "system_diagnostics": getattr(report, "system_diagnostics", {}),
    }
    rendered = json.dumps(result, indent=2)
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        **{key: value for key, value in result.items() if key != "change_audit"},
        "change_audit": {
            key: value for key, value in result["change_audit"].items()
            if key not in {"changed_step_ids", "unexpected_step_ids"}
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
