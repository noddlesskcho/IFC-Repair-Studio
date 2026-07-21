from __future__ import annotations

import hashlib
import mmap
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import CancelledError, OutputError


_SHAPE_KEYWORD = re.compile(rb"IFCSHAPEREPRESENTATION", re.I)
_RECORD_PREFIX = re.compile(rb"[ \t\r\n]*#(\d+)\s*=\s*$", re.I)
_FIRST_ARGUMENT = re.compile(rb"\s*\(\s*(\$|#\d+)", re.I)
_FINGERPRINT_BYTES = 64 * 1024
_COPY_CHUNK = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    size: int
    modified_ns: int
    edge_sha256: str


@dataclass(frozen=True, slots=True)
class PatchEdit:
    step_id: int
    context_step_id: int
    token_start: int
    token_end: int
    record_start: int
    record_end: int
    replacement: bytes


@dataclass(frozen=True, slots=True)
class PatchPlan:
    source: Path
    fingerprint: SourceFingerprint
    edits: tuple[PatchEdit, ...]
    expected_output_size: int


@dataclass(slots=True)
class PatchWriteResult:
    patched: int
    bytes_processed: int
    bytes_written: int
    write_seconds: float
    flush_seconds: float
    throughput_bytes_per_second: float
    token_positions: dict[int, tuple[int, int]]
    record_positions: dict[int, tuple[int, int]]


def source_fingerprint(path: Path) -> SourceFingerprint:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        digest.update(stream.read(_FINGERPRINT_BYTES))
        if stat.st_size > _FINGERPRINT_BYTES:
            stream.seek(max(0, stat.st_size - _FINGERPRINT_BYTES))
            digest.update(stream.read(_FINGERPRINT_BYTES))
    return SourceFingerprint(stat.st_size, stat.st_mtime_ns, digest.hexdigest())


def _record_end(mapped: mmap.mmap, start: int) -> int:
    """Return the byte after the terminating semicolon, respecting STEP strings/comments."""
    cursor = start
    quoted = False
    comment = False
    size = len(mapped)
    while cursor < size:
        current = mapped[cursor]
        following = mapped[cursor + 1] if cursor + 1 < size else -1
        if comment:
            if current == 42 and following == 47:  # */
                comment = False
                cursor += 2
                continue
        elif quoted:
            if current == 39:  # apostrophe; doubled apostrophes escape a quote
                if following == 39:
                    cursor += 2
                    continue
                quoted = False
        else:
            if current == 47 and following == 42:  # /*
                comment = True
                cursor += 2
                continue
            if current == 39:
                quoted = True
            elif current == 59:  # ;
                return cursor + 1
        cursor += 1
    raise OutputError("Target STEP record is truncated before its terminating semicolon")


def _shape_context_matches(mapped: mmap.mmap):
    """Yield shape STEP ID and first-argument offsets using a narrow keyword scan.

    Searching only the entity keyword avoids applying a complex anchored expression to
    every byte of a multi-gigabyte file. Prefix and first-argument syntax are then
    checked in small bounded record slices.
    """
    for keyword in _SHAPE_KEYWORD.finditer(mapped):
        record_start = mapped.rfind(b";", 0, keyword.start()) + 1
        prefix = mapped[record_start:keyword.start()]
        prefix_match = _RECORD_PREFIX.fullmatch(prefix)
        if not prefix_match:
            continue
        argument_match = _FIRST_ARGUMENT.match(
            mapped, keyword.end(), min(len(mapped), keyword.end() + 4096)
        )
        if not argument_match:
            continue
        hash_offset = prefix.find(b"#")
        yield (
            int(prefix_match.group(1)),
            argument_match.group(1),
            argument_match.start(1),
            argument_match.end(1),
            record_start + hash_offset,
        )


def build_patch_plan(
    source: Path,
    replacements: Mapping[int, int],
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> PatchPlan:
    """Locate exact first-argument tokens without changing or loading the source file."""
    source = source.resolve()
    if not replacements:
        raise OutputError("No targeted replacements were supplied")
    if any(step_id <= 0 or context_id <= 0 for step_id, context_id in replacements.items()):
        raise OutputError("STEP IDs and context references must be positive integers")

    fingerprint = source_fingerprint(source)
    edits: list[PatchEdit] = []
    found: set[int] = set()
    total = len(replacements)
    with source.open("rb") as stream, mmap.mmap(
        stream.fileno(), length=0, access=mmap.ACCESS_READ
    ) as mapped:
        for step_id, context_token, token_start, token_end, record_start in _shape_context_matches(mapped):
            if step_id not in replacements:
                continue
            if cancelled and cancelled():
                raise CancelledError("Repair cancelled while building the patch plan")
            if step_id in found:
                raise OutputError(f"Duplicate IfcShapeRepresentation STEP ID #{step_id}")
            if context_token != b"$":
                raise OutputError(
                    f"Confirmed representation #{step_id} no longer has an unset context"
                )
            edits.append(PatchEdit(
                step_id=step_id,
                context_step_id=int(replacements[step_id]),
                token_start=token_start,
                token_end=token_end,
                record_start=record_start,
                record_end=_record_end(mapped, record_start),
                replacement=f"#{int(replacements[step_id])}".encode("ascii"),
            ))
            found.add(step_id)
            if progress:
                progress(len(found), total)

    missing = sorted(set(replacements) - found)
    if missing:
        preview = ", ".join(f"#{value}" for value in missing[:8])
        suffix = "..." if len(missing) > 8 else ""
        raise OutputError(
            f"Could not locate {len(missing)} confirmed slab representation(s): "
            f"{preview}{suffix}"
        )
    edits.sort(key=lambda edit: edit.token_start)
    delta = sum(len(edit.replacement) - (edit.token_end - edit.token_start) for edit in edits)
    return PatchPlan(source, fingerprint, tuple(edits), fingerprint.size + delta)


def validate_patch_plan(plan: PatchPlan) -> None:
    if not plan.edits:
        raise OutputError("Patch plan is empty")
    previous_end = -1
    seen: set[int] = set()
    for edit in plan.edits:
        if edit.step_id in seen:
            raise OutputError(f"Duplicate patch target #{edit.step_id}")
        if not (0 <= edit.record_start <= edit.token_start < edit.token_end <= edit.record_end <= plan.fingerprint.size):
            raise OutputError(f"Invalid patch offsets for STEP ID #{edit.step_id}")
        if edit.token_start < previous_end:
            raise OutputError(f"Overlapping patch detected at STEP ID #{edit.step_id}")
        if not re.fullmatch(rb"#\d+", edit.replacement):
            raise OutputError(f"Invalid STEP replacement token for #{edit.step_id}")
        seen.add(edit.step_id)
        previous_end = edit.token_end


def _assert_source_unchanged(plan: PatchPlan) -> None:
    if source_fingerprint(plan.source) != plan.fingerprint:
        raise OutputError("Source IFC changed after the patch plan was created")


def apply_patch_plan(
    plan: PatchPlan,
    temporary: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int, int, int], None] | None = None,
) -> PatchWriteResult:
    """Stream-copy source to a new file and apply ordered variable-length token edits."""
    validate_patch_plan(plan)
    _assert_source_unchanged(plan)
    write_started = time.perf_counter()
    token_positions: dict[int, tuple[int, int]] = {}
    record_positions: dict[int, tuple[int, int]] = {}
    source_done = 0
    patches_done = 0

    def report_progress() -> None:
        if progress:
            progress(source_done, plan.fingerprint.size, patches_done, len(plan.edits))

    with plan.source.open("rb") as source_stream, mmap.mmap(
        source_stream.fileno(), length=0, access=mmap.ACCESS_READ
    ) as mapped, temporary.open("wb") as destination:
        cursor = 0
        output_delta = 0
        for edit in plan.edits:
            while cursor < edit.token_start:
                if cancelled and cancelled():
                    raise CancelledError("Repair cancelled while creating temporary output")
                end = min(edit.token_start, cursor + _COPY_CHUNK)
                view = memoryview(mapped)[cursor:end]
                try:
                    destination.write(view)
                finally:
                    view.release()
                cursor = end
                source_done = cursor
                report_progress()

            output_token_start = edit.token_start + output_delta
            destination.write(edit.replacement)
            token_positions[edit.step_id] = (
                output_token_start, output_token_start + len(edit.replacement)
            )
            delta_before = output_delta
            output_delta += len(edit.replacement) - (edit.token_end - edit.token_start)
            record_positions[edit.step_id] = (
                edit.record_start + delta_before,
                edit.record_end + output_delta,
            )
            cursor = edit.token_end
            source_done = cursor
            patches_done += 1
            report_progress()

        while cursor < len(mapped):
            if cancelled and cancelled():
                raise CancelledError("Repair cancelled while creating temporary output")
            end = min(len(mapped), cursor + _COPY_CHUNK)
            view = memoryview(mapped)[cursor:end]
            try:
                destination.write(view)
            finally:
                view.release()
            cursor = end
            source_done = cursor
            report_progress()

        write_finished = time.perf_counter()
        destination.flush()
        os.fsync(destination.fileno())
        flush_finished = time.perf_counter()

    _assert_source_unchanged(plan)
    write_seconds = write_finished - write_started
    flush_seconds = flush_finished - write_finished
    return PatchWriteResult(
        patched=len(plan.edits),
        bytes_processed=plan.fingerprint.size,
        bytes_written=plan.expected_output_size,
        write_seconds=write_seconds,
        flush_seconds=flush_seconds,
        throughput_bytes_per_second=(plan.fingerprint.size / write_seconds if write_seconds else 0.0),
        token_positions=token_positions,
        record_positions=record_positions,
    )


def targeted_step_patch(
    source: Path,
    temporary: Path,
    replacements: dict[int, int],
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    manifest: dict[int, tuple[int, int]] | None = None,
) -> int:
    """Compatibility wrapper around the explicit plan/validate/stream pipeline."""
    plan = build_patch_plan(source, replacements, cancelled=cancelled)
    validate_patch_plan(plan)

    def adapted(done: int, total: int, _patches: int, _patch_total: int) -> None:
        if progress:
            progress(done, total)

    result = apply_patch_plan(plan, temporary, cancelled=cancelled, progress=adapted)
    if manifest is not None:
        manifest.update(result.token_positions)
    return result.patched
