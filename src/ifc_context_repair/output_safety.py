from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path

from .errors import OutputError, ResourceError


def cleanup_abandoned_temps(
    directory: Path, *, older_than_hours: float = 24.0, output_stem: str | None = None,
) -> list[Path]:
    """Remove only this application's hidden `.tmp.ifc` files older than the threshold."""
    removed: list[Path] = []
    if not directory.is_dir():
        return removed
    cutoff = time.time() - max(1.0, older_than_hours) * 3600
    pattern = f".{output_stem}.*.tmp.ifc" if output_stem else ".*.*.tmp.ifc"
    for candidate in directory.glob(pattern):
        try:
            if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                candidate.unlink()
                removed.append(candidate)
        except OSError:
            continue
    return removed


def preflight_output(
    source: Path,
    output: Path,
    *,
    replace_original: bool,
    safety_factor: float = 1.2,
    safety_margin_mb: int = 64,
) -> dict[str, int | bool]:
    directory = output.parent
    if not directory.is_dir():
        raise OutputError(f"Output directory does not exist: {directory}")
    probe = directory / f".ifc-repair-write-test-{uuid.uuid4().hex}.tmp"
    try:
        with probe.open("xb") as stream:
            stream.write(b"ok")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise OutputError(f"Output directory is not writable: {directory}: {exc}") from exc
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass

    if output.exists() and output != source:
        try:
            with output.open("r+b"):
                pass
        except OSError as exc:
            raise OutputError(f"Destination appears locked or unavailable: {output}: {exc}") from exc

    source_size = source.stat().st_size
    multiplier = max(1.0, safety_factor) + (1.0 if replace_original else 0.0)
    required = int(source_size * multiplier) + max(0, safety_margin_mb) * 1024 * 1024
    free = shutil.disk_usage(directory).free
    if free < required:
        raise ResourceError(
            f"Insufficient free space. {required:,} bytes required; {free:,} bytes available."
        )
    return {
        "source_size": source_size,
        "required_free_bytes": required,
        "available_free_bytes": free,
        "output_directory_writable": True,
        "destination_lock_check_passed": True,
    }
