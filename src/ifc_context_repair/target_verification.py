from __future__ import annotations

import mmap
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CancelledError
from .step_patch import PatchPlan, PatchWriteResult


_SHAPE_CONTEXT = re.compile(
    rb"(?:^|(?<=;))[ \t\r\n]*#(\d+)\s*=\s*IFCSHAPEREPRESENTATION\s*\(\s*(\$|#\d+)",
    re.I | re.M,
)


@dataclass(slots=True)
class TargetVerificationResult:
    passed: bool
    intended: int
    verified: int
    remaining: int
    file_size: int
    header_valid: bool
    footer_valid: bool
    messages: list[str] = field(default_factory=list)
    data_valid: bool = False
    endsec_valid: bool = False
    plausible_size: bool = False
    records_unchanged_except_context: bool = False
    wrong_step_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class StepEnvelopeResult:
    file_size: int
    header_valid: bool
    data_valid: bool
    endsec_valid: bool
    footer_valid: bool
    plausible_size: bool


def verify_step_envelope(path: Path, expected_size: int | None = None) -> StepEnvelopeResult:
    """Verify the bounded STEP envelope without parsing or reading the whole file."""
    size = path.stat().st_size if path.exists() else 0
    if size <= 0:
        return StepEnvelopeResult(size, False, False, False, False, False)
    with path.open("rb") as stream, mmap.mmap(
        stream.fileno(), length=0, access=mmap.ACCESS_READ
    ) as mapped:
        start = mapped[: min(size, 1024 * 1024)].upper()
        end = mapped[max(0, size - 8192):].upper()
        return StepEnvelopeResult(
            file_size=size,
            header_valid=b"ISO-10303-21" in start and b"HEADER" in start,
            data_valid=b"DATA" in start,
            endsec_valid=b"ENDSEC" in end,
            footer_valid=b"END-ISO-10303-21" in end,
            plausible_size=expected_size is None or size == expected_size,
        )


def verify_targeted_output(
    path: Path,
    replacements: dict[int, int],
    positions: dict[int, tuple[int, int]] | None = None,
    *,
    source: Path | None = None,
    plan: PatchPlan | None = None,
    write_result: PatchWriteResult | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    envelope: StepEnvelopeResult | None = None,
) -> TargetVerificationResult:
    size = path.stat().st_size if path.exists() else 0
    if size <= 0:
        return TargetVerificationResult(
            False, len(replacements), 0, len(replacements), size, False, False,
            ["Temporary output is missing or empty"],
        )
    if write_result is not None:
        positions = write_result.token_positions
    verified: set[int] = set()
    wrong: list[int] = []
    record_integrity = True
    expected_size = plan.expected_output_size if plan else None

    envelope = envelope or verify_step_envelope(path, expected_size)
    header_valid = envelope.header_valid
    data_valid = envelope.data_valid
    endsec_valid = envelope.endsec_valid
    footer_valid = envelope.footer_valid
    plausible_size = envelope.plausible_size

    with path.open("rb") as stream, mmap.mmap(
        stream.fileno(), length=0, access=mmap.ACCESS_READ
    ) as mapped:
        if positions is not None:
            for index, (step_id, expected) in enumerate(replacements.items(), 1):
                if cancelled and cancelled():
                    raise CancelledError("Repair cancelled while verifying target records")
                bounds = positions.get(step_id)
                if not bounds or bounds[0] < 0 or bounds[1] > size:
                    wrong.append(step_id)
                    continue
                actual = mapped[bounds[0]:bounds[1]]
                if actual == f"#{expected}".encode("ascii"):
                    verified.add(step_id)
                else:
                    wrong.append(step_id)
                if progress and (index % 100 == 0 or index == len(replacements)):
                    progress(index, len(replacements))
        else:
            occurrences: dict[int, list[bytes]] = {}
            for match in _SHAPE_CONTEXT.finditer(mapped):
                step_id = int(match.group(1))
                if step_id in replacements:
                    occurrences.setdefault(step_id, []).append(match.group(2))
            for index, (step_id, expected) in enumerate(replacements.items(), 1):
                values = occurrences.get(step_id, [])
                if values == [f"#{expected}".encode("ascii")]:
                    verified.add(step_id)
                else:
                    wrong.append(step_id)
                if progress and (index % 100 == 0 or index == len(replacements)):
                    progress(index, len(replacements))

        if source is not None and plan is not None and write_result is not None:
            with source.open("rb") as source_stream, mmap.mmap(
                source_stream.fileno(), length=0, access=mmap.ACCESS_READ
            ) as source_map:
                for edit in plan.edits:
                    output_bounds = write_result.record_positions.get(edit.step_id)
                    if not output_bounds:
                        record_integrity = False
                        if edit.step_id not in wrong:
                            wrong.append(edit.step_id)
                        continue
                    original = source_map[edit.record_start:edit.record_end]
                    relative_start = edit.token_start - edit.record_start
                    relative_end = edit.token_end - edit.record_start
                    expected_record = (
                        original[:relative_start] + edit.replacement + original[relative_end:]
                    )
                    actual_record = mapped[output_bounds[0]:output_bounds[1]]
                    if actual_record != expected_record:
                        record_integrity = False
                        if edit.step_id not in wrong:
                            wrong.append(edit.step_id)
        elif plan is None:
            record_integrity = True  # compatibility verification has no source plan

    remaining = len(replacements) - len(verified)
    messages: list[str] = []
    if not header_valid:
        messages.append("ISO-10303-21/HEADER envelope was not found")
    if not data_valid:
        messages.append("DATA section was not found")
    if not endsec_valid:
        messages.append("ENDSEC marker was not found near the end of the file")
    if not footer_valid:
        messages.append("END-ISO-10303-21 footer was not found")
    if not plausible_size:
        messages.append(f"Output size {size:,} does not match expected size {expected_size:,}")
    if remaining:
        messages.append(f"{remaining} intended target assignment(s) were not verified")
    if wrong:
        messages.append(f"{len(set(wrong))} target record(s) differ from the exact planned change")
    if not record_integrity:
        messages.append("One or more target records changed outside ContextOfItems")
    passed = all((header_valid, data_valid, endsec_valid, footer_valid, plausible_size,
                  remaining == 0, not wrong, record_integrity))
    return TargetVerificationResult(
        passed, len(replacements), len(verified), remaining, size,
        header_valid, footer_valid, messages, data_valid, endsec_valid,
        plausible_size, record_integrity, sorted(set(wrong)),
    )
