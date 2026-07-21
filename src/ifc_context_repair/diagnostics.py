from __future__ import annotations

import json
import ctypes
import os
import threading
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _windows_memory_snapshot() -> dict[str, int | None]:
    if os.name != "nt":
        return {}

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong), ("page_faults", ctypes.c_ulong),
            ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
            ("quota_peak_paged", ctypes.c_size_t), ("quota_paged", ctypes.c_size_t),
            ("quota_peak_nonpaged", ctypes.c_size_t), ("quota_nonpaged", ctypes.c_size_t),
            ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t),
            ("private_usage", ctypes.c_size_t),
        ]

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    try:
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        memory_ok = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        system_ok = kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return {
            "process_working_set_bytes": int(counters.working_set) if memory_ok else None,
            "process_peak_working_set_bytes": int(counters.peak_working_set) if memory_ok else None,
            "process_virtual_memory_bytes": int(counters.private_usage) if memory_ok else None,
            "system_available_memory_bytes": int(status.available_physical) if system_ok else None,
        }
    except Exception:
        return {}


def system_snapshot(path: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "process_working_set_bytes": None,
        "process_peak_working_set_bytes": None,
        "process_virtual_memory_bytes": None,
        "system_available_memory_bytes": None,
        "cpu_percent": None,
        "thread_count": threading.active_count(),
        "disk_free_bytes": shutil.disk_usage(path or Path.cwd()).free,
        "psutil_available": False,
    }
    result.update(_windows_memory_snapshot())
    try:
        import psutil
        process = psutil.Process()
        memory = process.memory_info()
        virtual = psutil.virtual_memory()
        result.update({
            "process_working_set_bytes": int(memory.rss),
            "process_peak_working_set_bytes": int(getattr(memory, "peak_wset", memory.rss)),
            "process_virtual_memory_bytes": int(memory.vms),
            "system_available_memory_bytes": int(virtual.available),
            "cpu_percent": float(process.cpu_percent(interval=None)),
            "thread_count": int(process.num_threads()),
            "psutil_available": True,
        })
    except Exception:
        pass
    return result


class DiagnosticLogger:
    """Opt-in JSON-lines diagnostics, isolated from user-facing report generation."""

    def __init__(
        self, path: Path, *, enabled: bool, source: Path, output: Path,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.path = path
        self.enabled = enabled
        self.source = source
        self.output = output
        self.max_bytes = max_bytes

    def _rotate(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
            return
        previous = self.path.with_suffix(self.path.suffix + ".1")
        if previous.exists():
            previous.unlink(missing_ok=True)
        self.path.replace(previous)

    def write(
        self, stage: str, status: str, *, duration: float | None = None,
        message: str = "", temporary: Path | None = None, **extra: Any,
    ) -> dict[str, Any]:
        snapshot = system_snapshot(self.output.parent)
        event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "status": status,
            "message": message,
            "thread": threading.current_thread().name,
            "thread_id": threading.get_ident(),
            "memory_bytes": snapshot["process_working_set_bytes"],
            "system": snapshot,
            "source": str(self.source),
            "output": str(self.output),
            "temporary": str(temporary) if temporary else None,
            **extra,
        }
        if duration is not None:
            event["duration_seconds"] = round(duration, 6)
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event
