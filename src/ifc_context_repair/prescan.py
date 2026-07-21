from __future__ import annotations

import mmap
import re
from collections.abc import Callable
from pathlib import Path

from .errors import CancelledError
from .models import PrescanCandidate


# STEP entities normally begin after a semicolon or at the start of the file.
# mmap lets the regex engine scan in native code without copying the IFC into
# Python memory. Capturing the first argument also avoids a second record parse.
_SHAPE_REPRESENTATION = re.compile(
    rb"(?:^|(?<=;))[ \t\r\n]*#(\d+)\s*=\s*IFCSHAPEREPRESENTATION\s*\(\s*([$#])",
    re.I | re.M,
)


def scan_step(
    path: str | Path,
    *,
    chunk_size: int = 1024 * 1024,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[PrescanCandidate]:
    """Quickly locate shape representations whose context is ``$``.

    The file is memory-mapped, so large IFCs are scanned without allocating a
    second in-memory copy. ``chunk_size`` controls callback frequency and is
    retained as part of the public API; it does not allocate a chunk buffer.
    """
    source = Path(path)
    total = source.stat().st_size
    if total == 0:
        if progress:
            progress(0, 0)
        return []

    candidates: list[PrescanCandidate] = []
    callback_interval = max(64 * 1024, chunk_size)
    next_callback = callback_interval
    line = 1
    line_cursor = 0

    with source.open("rb") as stream, mmap.mmap(
        stream.fileno(), length=0, access=mmap.ACCESS_READ
    ) as mapped:
        for match in _SHAPE_REPRESENTATION.finditer(mapped):
            record_offset = match.start(1) - 1  # include the leading '#'

            if record_offset >= next_callback:
                if cancelled and cancelled():
                    raise CancelledError("Scan cancelled")
                if progress:
                    progress(record_offset, total)
                next_callback = record_offset + callback_interval

            if match.group(2) != b"$":
                continue

            stream.seek(line_cursor)
            remaining = record_offset - line_cursor
            while remaining:
                block = stream.read(min(callback_interval, remaining))
                if not block:
                    break
                line += block.count(b"\n")
                remaining -= len(block)
            line_cursor = record_offset
            preview_end = min(total, record_offset + 300)
            candidates.append(
                PrescanCandidate(
                    step_id=int(match.group(1)),
                    byte_offset=record_offset,
                    line_number=line,
                    record_preview=mapped[record_offset:preview_end].decode(
                        "latin-1", "replace"
                    ),
                )
            )

        if cancelled and cancelled():
            raise CancelledError("Scan cancelled")
        if progress:
            progress(total, total)

    return candidates
