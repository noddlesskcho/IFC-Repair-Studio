from __future__ import annotations

import mmap
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CancelledError
from .step_patch import PatchPlan, PatchWriteResult


_STEP_ID = re.compile(rb"#(\d+)\s*=", re.I)
_CHUNK = 8 * 1024 * 1024


@dataclass(slots=True)
class ChangeAuditResult:
    passed: bool
    expected_modified_records: int
    actual_modified_records: int
    unexpected_modified_records: int
    changed_step_ids: list[int] = field(default_factory=list)
    unexpected_step_ids: list[int] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _step_id_at(mapped: mmap.mmap, offset: int) -> int | None:
    start = mapped.rfind(b";", 0, max(0, offset)) + 1
    match = _STEP_ID.search(mapped, start, min(len(mapped), start + 512))
    return int(match.group(1)) if match else None


def audit_targeted_changes(
    source: Path,
    output: Path,
    plan: PatchPlan,
    write_result: PatchWriteResult,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ChangeAuditResult:
    """Prove all bytes outside intended ContextOfItems tokens are unchanged."""
    expected = [edit.step_id for edit in plan.edits]
    unexpected: set[int] = set()
    messages: list[str] = []
    compared = 0
    total = plan.fingerprint.size - sum(edit.token_end - edit.token_start for edit in plan.edits)

    with source.open("rb") as source_file, output.open("rb") as output_file, mmap.mmap(
        source_file.fileno(), 0, access=mmap.ACCESS_READ
    ) as source_map, mmap.mmap(output_file.fileno(), 0, access=mmap.ACCESS_READ) as output_map:
        source_cursor = 0
        output_cursor = 0
        ranges: list[tuple[int, int, int, int]] = []
        for edit in plan.edits:
            output_token = write_result.token_positions[edit.step_id]
            ranges.append((source_cursor, edit.token_start, output_cursor, output_token[0]))
            source_cursor = edit.token_end
            output_cursor = output_token[1]
        ranges.append((source_cursor, len(source_map), output_cursor, len(output_map)))

        for source_start, source_end, output_start, output_end in ranges:
            if source_end - source_start != output_end - output_start:
                messages.append("Unchanged byte ranges have inconsistent lengths")
                return ChangeAuditResult(False, len(expected), len(expected) + 1, 1, expected, [], messages)
            source_pos, output_pos = source_start, output_start
            while source_pos < source_end:
                if cancelled and cancelled():
                    raise CancelledError("Repair cancelled during unintended-change audit")
                amount = min(_CHUNK, source_end - source_pos)
                source_chunk = source_map[source_pos:source_pos + amount]
                output_chunk = output_map[output_pos:output_pos + amount]
                if source_chunk != output_chunk:
                    difference = next(
                        (index for index, pair in enumerate(zip(source_chunk, output_chunk)) if pair[0] != pair[1]),
                        0,
                    )
                    step_id = _step_id_at(source_map, source_pos + difference)
                    if step_id is not None and step_id not in expected:
                        unexpected.add(step_id)
                    messages.append(
                        f"Unexpected byte difference near source offset {source_pos + difference}"
                    )
                    if len(messages) >= 20:
                        break
                source_pos += amount
                output_pos += amount
                compared += amount
                if progress:
                    progress(compared, max(1, total))
            if len(messages) >= 20:
                break

    passed = not messages and not unexpected
    unexpected_count = len(unexpected) if unexpected else (1 if messages else 0)
    return ChangeAuditResult(
        passed=passed,
        expected_modified_records=len(expected),
        actual_modified_records=len(expected) + unexpected_count,
        unexpected_modified_records=unexpected_count,
        changed_step_ids=expected + sorted(unexpected),
        unexpected_step_ids=sorted(unexpected),
        messages=messages,
    )
