from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .naming import default_repaired_path
from .feature_flags import RepairFeatureFlags


@dataclass(slots=True)
class RepairConfig:
    source: Path
    output: Path | None = None
    output_dir: Path | None = None
    create_backup: bool = False
    include_warnings: bool = False
    geometry_test: bool = False
    repair_mode: str = "production"
    max_file_size_gb: float | None = None
    overwrite_output: bool = False
    selected_step_ids: set[int] | None = None
    replace_original_with_backup: bool = False
    full_validation: bool = False
    generate_report: bool = True
    debug_logging: bool = False
    verbose_debug_logging: bool = False
    disk_safety_factor: float = 1.2
    disk_safety_margin_mb: int = 64
    abandoned_temp_age_hours: float = 24.0
    minimum_confidence: float = 0.70
    rule_id: str = "DIRECT_PRODUCT_MISSING_CONTEXT_V1"
    feature_flags: RepairFeatureFlags = field(
        default_factory=RepairFeatureFlags.version_1
    )
    developer_mode: bool = False

    def resolved_output(self) -> Path:
        if self.replace_original_with_backup:
            return self.source.resolve()
        if self.output:
            return self.output.resolve()
        if self.output_dir:
            candidate = self.output_dir.resolve() / f"{self.source.stem}_repaired{self.source.suffix}"
            counter = 2
            while candidate.exists():
                candidate = self.output_dir.resolve() / (
                    f"{self.source.stem}_repaired_{counter}{self.source.suffix}"
                )
                counter += 1
            return candidate
        return default_repaired_path(self.source.resolve())
