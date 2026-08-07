from __future__ import annotations

import hashlib
import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import CancelledError
from .feature_flags import RepairFeatureFlags
from .models import RunReport
from .step_patch import SourceFingerprint


_HASH_CHUNK = 8 * 1024 * 1024


def source_sha256(
    path: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    """Hash a source without loading it into Python memory."""
    total = path.stat().st_size
    processed = 0
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            if cancelled and cancelled():
                raise CancelledError("Operation cancelled while verifying the reviewed IFC")
            block = stream.read(_HASH_CHUNK)
            if not block:
                break
            digest.update(block)
            processed += len(block)
            if progress:
                progress(processed, total)
    if progress and processed == 0:
        progress(0, total)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedRepairAnalysis:
    """Compact, detached result of a completed semantic review.

    The report is stored as an internal immutable byte snapshot.  No
    IfcOpenShell model or entity handle survives the review job.
    """

    source_fingerprint: SourceFingerprint
    source_sha256: str
    semantic_counts: tuple[tuple[str, int], ...]
    repair_mode: str
    feature_flags: RepairFeatureFlags
    full_validation: bool
    _report_snapshot: RunReport

    @classmethod
    def create(
        cls,
        *,
        source_fingerprint: SourceFingerprint,
        source_sha256_value: str,
        semantic_counts: dict[str, int],
        repair_mode: str,
        feature_flags: RepairFeatureFlags,
        full_validation: bool,
        report: RunReport,
    ) -> "PreparedRepairAnalysis":
        return cls(
            source_fingerprint=source_fingerprint,
            source_sha256=source_sha256_value,
            semantic_counts=tuple(sorted(semantic_counts.items())),
            repair_mode=repair_mode.casefold(),
            feature_flags=feature_flags,
            full_validation=full_validation,
            _report_snapshot=copy.deepcopy(report),
        )

    def report_copy(self) -> RunReport:
        report = copy.deepcopy(self._report_snapshot)
        if not isinstance(report, RunReport):
            raise TypeError("Prepared analysis does not contain a RunReport")
        return report

    def semantic_count_dict(self) -> dict[str, int]:
        return dict(self.semantic_counts)
