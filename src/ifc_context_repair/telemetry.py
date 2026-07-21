from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class StageUpdate:
    stage_id: str
    message: str
    current: int | None = None
    total: int | None = None
    indeterminate: bool = False
    temporary_path: Path | None = None
    output_size: int | None = None
    cancellable: bool = True
    bytes_processed: int | None = None
    bytes_total: int | None = None
    elapsed_seconds: float | None = None
    throughput_bytes_per_second: float | None = None
    estimated_remaining_seconds: float | None = None


ProgressUpdate = StageUpdate


Telemetry = Callable[[StageUpdate], None]


def emit(callback: Telemetry | None, stage_id: str, message: str, **kwargs: object) -> None:
    if callback:
        callback(StageUpdate(stage_id=stage_id, message=message, **kwargs))
