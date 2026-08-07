from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RepairFeatureFlags:
    """Repair-category switches captured once when a job is created.

    Version 1 exposes only direct-product repair. Indirect categories remain
    available to tests and developer diagnostics, but a non-developer job can
    never activate them through configuration data.
    """

    enable_direct_product_repairs: bool = True
    enable_shape_aspect_repairs: bool = False
    enable_representation_map_repairs: bool = False

    @classmethod
    def version_1(cls) -> "RepairFeatureFlags":
        return cls()

    @classmethod
    def from_internal_config(
        cls,
        value: Mapping[str, Any] | None,
        *,
        developer_mode: bool = False,
    ) -> "RepairFeatureFlags":
        rules = dict((value or {}).get("repair_rules", {}))
        direct = bool(rules.get("direct_product_missing_context", True))
        if not developer_mode:
            return cls(enable_direct_product_repairs=direct)
        return cls(
            enable_direct_product_repairs=direct,
            enable_shape_aspect_repairs=bool(
                rules.get("shape_aspect_missing_context", False)
            ),
            enable_representation_map_repairs=bool(
                rules.get("representation_map_missing_context", False)
            ),
        )

    def protected(self, *, developer_mode: bool) -> "RepairFeatureFlags":
        if developer_mode:
            return self
        return RepairFeatureFlags(
            enable_direct_product_repairs=self.enable_direct_product_repairs
        )

    @property
    def indirect_enabled(self) -> bool:
        return (
            self.enable_shape_aspect_repairs
            or self.enable_representation_map_repairs
        )

    def to_internal_config(self) -> dict[str, dict[str, bool]]:
        return {
            "repair_rules": {
                "direct_product_missing_context": (
                    self.enable_direct_product_repairs
                ),
                "shape_aspect_missing_context": (
                    self.enable_shape_aspect_repairs
                ),
                "representation_map_missing_context": (
                    self.enable_representation_map_repairs
                ),
            }
        }
