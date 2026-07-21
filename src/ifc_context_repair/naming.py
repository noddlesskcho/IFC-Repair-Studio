from __future__ import annotations

from datetime import datetime
from pathlib import Path


def default_repaired_path(source: Path) -> Path:
    """Return the first deterministic, non-existing repaired output path."""
    candidate = source.with_name(f"{source.stem}_repaired{source.suffix}")
    counter = 2
    while candidate.exists():
        candidate = source.with_name(
            f"{source.stem}_repaired_{counter}{source.suffix}"
        )
        counter += 1
    return candidate


def overwrite_backup_path(source: Path, now: datetime | None = None) -> Path:
    """Choose a stable overwrite backup name without repeated `_backup` suffixes."""
    first = source.with_name(f"{source.stem}.original{source.suffix}")
    if not first.exists():
        return first
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    candidate = source.with_name(f"{source.stem}.original_{stamp}{source.suffix}")
    counter = 2
    while candidate.exists():
        candidate = source.with_name(
            f"{source.stem}.original_{stamp}_{counter}{source.suffix}"
        )
        counter += 1
    return candidate
