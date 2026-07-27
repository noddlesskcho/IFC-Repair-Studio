from __future__ import annotations

import mmap
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CancelledError
from .models import PrescanCandidate


# STEP entities normally begin after a semicolon or at the start of the file.
# mmap lets the regex engine scan in native code without copying the IFC into
# Python memory. Capturing the first argument also avoids a second record parse.
_SHAPE_KEYWORD = re.compile(rb"IFCSHAPEREPRESENTATION", re.I)
_RECORD_PREFIX = re.compile(rb"[ \t\r\n]*#(\d+)\s*=\s*$", re.I)
_FIRST_ARGUMENT = re.compile(rb"\s*\(\s*(\$|#\d+)", re.I)
_FILE_SCHEMA = re.compile(
    rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", re.I
)
_HEADER_FIELD = re.compile(
    rb"FILE_NAME\s*\((.*?)\)\s*;", re.I | re.S
)
_MISSING_SHAPE_SIGNATURE = re.compile(
    rb"IFCSHAPEREPRESENTATION\s*\(\s*\$\s*,\s*'([^']*)'\s*,\s*'([^']*)'",
    re.I,
)
_RELEVANT_TYPES = frozenset({
    "IFCSHAPEREPRESENTATION",
    "IFCSHAPEASPECT",
    "IFCREPRESENTATIONMAP",
    "IFCSPACE",
    "IFCELEMENTQUANTITY",
    "IFCPROJECTEDCRS",
    "IFCMAPCONVERSION",
    "IFCPROPERTYSET",
})


@dataclass(slots=True)
class StepPrescanProfile:
    schema: str | None
    file_size: int
    entity_counts: dict[str, int] = field(default_factory=dict)
    missing_context_signatures: dict[str, int] = field(default_factory=dict)
    exporter_text: str = ""
    has_sg_psets: bool = False
    candidates: list[PrescanCandidate] = field(default_factory=list)


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
        for keyword in _SHAPE_KEYWORD.finditer(mapped):
            record_start = mapped.rfind(b";", 0, keyword.start()) + 1
            prefix = mapped[record_start:keyword.start()]
            prefix_match = _RECORD_PREFIX.fullmatch(prefix)
            if not prefix_match:
                continue
            argument_match = _FIRST_ARGUMENT.match(
                mapped,
                keyword.end(),
                min(total, keyword.end() + 4096),
            )
            if not argument_match:
                continue
            hash_offset = prefix.find(b"#")
            record_offset = record_start + hash_offset

            if record_offset >= next_callback:
                if cancelled and cancelled():
                    raise CancelledError("Scan cancelled")
                if progress:
                    progress(record_offset, total)
                next_callback = record_offset + callback_interval

            if argument_match.group(1) != b"$":
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
                    step_id=int(prefix_match.group(1)),
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


def profile_step(
    path: str | Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> StepPrescanProfile:
    """Build the lightweight IFC+SG routing profile without semantic loading."""
    source = Path(path)
    total = source.stat().st_size
    candidates = scan_step(
        source, cancelled=cancelled, progress=progress,
    )
    counts: Counter[str] = Counter()
    signatures: Counter[str] = Counter()
    schema: str | None = None
    exporter_text = ""
    has_sg_psets = False
    with source.open("rb") as stream, mmap.mmap(
        stream.fileno(), length=0, access=mmap.ACCESS_READ
    ) as mapped:
        header_end = mapped.find(b"DATA;")
        header = mapped[: min(
            total, header_end + 5 if header_end >= 0 else 1024 * 1024
        )]
        schema_match = _FILE_SCHEMA.search(header)
        if schema_match:
            schema = schema_match.group(1).decode("ascii", "replace").upper()
        name_match = _HEADER_FIELD.search(header)
        if name_match:
            exporter_text = name_match.group(1).decode("latin-1", "replace")[:4000]
        has_sg_psets = (
            mapped.find(b"SGPset_") >= 0
            or mapped.find(b"SGPSET_") >= 0
            or mapped.find(b"IFC+SG") >= 0
        )
        seen_step_ids = bytearray()
        sparse_step_ids: set[int] = set()
        duplicate_step_ids = 0
        stream.seek(0)
        for raw_line in stream:
            if cancelled and cancelled():
                raise CancelledError("Pre-scan cancelled")
            line = raw_line.lstrip()
            if not line.startswith(b"#"):
                continue
            equals = line.find(b"=")
            if equals <= 1:
                continue
            try:
                entity_id = int(line[1:equals].strip())
            except ValueError:
                continue
            tail = line[equals + 1:].lstrip()
            opening = tail.find(b"(")
            if opening <= 0:
                continue
            entity_name = tail[:opening].strip().decode(
                "ascii", "replace"
            ).upper()
            byte_index, bit = divmod(entity_id, 8)
            if byte_index > 16 * 1024 * 1024:
                if entity_id in sparse_step_ids:
                    duplicate_step_ids += 1
                else:
                    sparse_step_ids.add(entity_id)
                if entity_name in _RELEVANT_TYPES:
                    counts[entity_name] += 1
                continue
            if byte_index >= len(seen_step_ids):
                seen_step_ids.extend(b"\0" * (byte_index + 1 - len(seen_step_ids)))
            mask = 1 << bit
            if seen_step_ids[byte_index] & mask:
                duplicate_step_ids += 1
            else:
                seen_step_ids[byte_index] |= mask
            if entity_name in _RELEVANT_TYPES:
                counts[entity_name] += 1
        counts["DUPLICATE_STEP_IDS"] = duplicate_step_ids
        for candidate in candidates:
            match = _MISSING_SHAPE_SIGNATURE.search(
                candidate.record_preview.encode("latin-1", "replace")
            )
            if not match:
                signatures["Unidentified / Unspecified"] += 1
                continue
            identifier = match.group(1).decode("latin-1", "replace") or "(unset)"
            representation_type = (
                match.group(2).decode("latin-1", "replace") or "(unset)"
            )
            signatures[f"{identifier} / {representation_type}"] += 1
    return StepPrescanProfile(
        schema=schema,
        file_size=total,
        entity_counts=dict(sorted(counts.items())),
        missing_context_signatures=dict(sorted(signatures.items())),
        exporter_text=exporter_text,
        has_sg_psets=has_sg_psets,
        candidates=candidates,
    )
