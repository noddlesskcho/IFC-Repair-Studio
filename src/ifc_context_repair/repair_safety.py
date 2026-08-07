from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .models import Diagnosis, RepresentationClassification
from .resources import resource_path


class RepairSafetyLevel(str, Enum):
    PRODUCTION_SAFE = "Production-Safe"
    EXPERIMENTAL = "Experimental"
    REPORT_ONLY = "Report Only"


class ViewerTestStatus(str, Enum):
    NOT_TESTED = "Not Tested"
    PASSED = "Passed"
    FAILED = "Failed"
    INCONCLUSIVE = "Inconclusive"


@dataclass(frozen=True, slots=True)
class SignatureStatus:
    signature: str
    safety_level: RepairSafetyLevel
    internal_verification: str
    corenet_x_viewer: ViewerTestStatus
    production_enabled: bool
    reason: str

    @classmethod
    def from_dict(cls, signature: str, value: dict[str, Any]) -> "SignatureStatus":
        return cls(
            signature=signature,
            safety_level=RepairSafetyLevel(
                value.get("safety_level", RepairSafetyLevel.REPORT_ONLY.value)
            ),
            internal_verification=str(
                value.get("internal_verification", "not_tested")
            ),
            corenet_x_viewer=ViewerTestStatus(
                value.get("corenet_x_viewer", ViewerTestStatus.NOT_TESTED.value)
            ),
            production_enabled=bool(value.get("production_enabled", False)),
            reason=str(value.get("reason", "No production approval is recorded.")),
        )

    @property
    def is_production_safe(self) -> bool:
        return (
            self.safety_level is RepairSafetyLevel.PRODUCTION_SAFE
            and self.internal_verification.casefold() == "passed"
            and self.corenet_x_viewer is ViewerTestStatus.PASSED
            and self.production_enabled
        )


_OWNER_NAMES = {
    RepresentationClassification.DIRECT_PRODUCT: "DirectProduct",
    RepresentationClassification.SHAPE_ASPECT_PRODUCT: "ShapeAspect",
    RepresentationClassification.SHAPE_ASPECT_REPRESENTATION_MAP: "ShapeAspectMap",
    RepresentationClassification.REPRESENTATION_MAP: "RepresentationMap",
    RepresentationClassification.ORPHANED: "Orphaned",
    RepresentationClassification.AMBIGUOUS: "Ambiguous",
    RepresentationClassification.UNSUPPORTED: "Unsupported",
}


def repair_signature(diagnosis: Diagnosis) -> str:
    owner = _OWNER_NAMES.get(diagnosis.classification, diagnosis.classification.value)
    raw_identifier = str(diagnosis.representation_identifier or "Unidentified")
    raw_type = str(diagnosis.representation_type or "Unspecified")
    identifier = {
        "body": "Body",
        "footprint": "FootPrint",
        "axis": "Axis",
    }.get(raw_identifier.casefold(), raw_identifier)
    representation_type = {
        "sweptsolid": "SweptSolid",
        "tessellation": "Tessellation",
        "curve2d": "Curve2D",
    }.get(raw_type.casefold(), raw_type)
    return f"{owner}/{identifier}/{representation_type}"


class RepairSafetyRegistry:
    """Explicit, persistent viewer-compatibility policy.

    Internal semantic verification never changes production enablement. The JSON
    registry must be deliberately updated after a controlled CORENET X Viewer test.
    """

    def __init__(self, entries: dict[str, SignatureStatus]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, path: Path | None = None) -> "RepairSafetyRegistry":
        registry_path = path or resource_path("assets/repair_signature_status.json")
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        return cls({
            signature: SignatureStatus.from_dict(signature, value)
            for signature, value in data.get("signatures", {}).items()
        })

    def status_for(self, diagnosis: Diagnosis) -> SignatureStatus:
        signature = repair_signature(diagnosis)
        configured = self._entries.get(signature)
        if configured is not None:
            return configured
        if diagnosis.classification in {
            RepresentationClassification.ORPHANED,
            RepresentationClassification.AMBIGUOUS,
            RepresentationClassification.UNSUPPORTED,
        }:
            reason = "Ownership or compatible context is not uniquely proven."
        else:
            reason = (
                "This repair signature has no successful CORENET X Viewer test record."
            )
        return SignatureStatus(
            signature=signature,
            safety_level=RepairSafetyLevel.REPORT_ONLY,
            internal_verification="not_tested",
            corenet_x_viewer=ViewerTestStatus.NOT_TESTED,
            production_enabled=False,
            reason=reason,
        )

    def metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "signature": item.signature,
                "safety_level": item.safety_level.value,
                "internal_verification": item.internal_verification,
                "corenet_x_viewer": item.corenet_x_viewer.value,
                "production_enabled": item.production_enabled,
                "reason": item.reason,
            }
            for item in sorted(self._entries.values(), key=lambda value: value.signature)
        ]


SAFETY_REGISTRY = RepairSafetyRegistry.load()

_RULE_BY_SIGNATURE = {
    "DirectProduct/Body/SweptSolid":
        "DIRECT_PRODUCT_BODY_SWEPTSOLID_MISSING_CONTEXT_V1",
    "DirectProduct/Body/Tessellation":
        "DIRECT_PRODUCT_BODY_TESSELLATION_MISSING_CONTEXT_V1",
    "DirectProduct/FootPrint/Curve2D":
        "DIRECT_PRODUCT_FOOTPRINT_CURVE2D_MISSING_CONTEXT_V1",
    "ShapeAspect/Body/SweptSolid":
        "SHAPE_ASPECT_PRODUCT_MISSING_CONTEXT_V1",
    "ShapeAspect/Body/Tessellation":
        "SHAPE_ASPECT_PRODUCT_MISSING_CONTEXT_V1",
    "RepresentationMap/FootPrint/Curve2D":
        "REPRESENTATION_MAP_FOOTPRINT_MISSING_CONTEXT_V1",
}


def apply_signature_policy(diagnosis: Diagnosis) -> SignatureStatus:
    status = SAFETY_REGISTRY.status_for(diagnosis)
    diagnosis.repair_signature = status.signature
    diagnosis.safety_level = status.safety_level.value
    diagnosis.viewer_test_status = status.corenet_x_viewer.value
    diagnosis.production_enabled = status.is_production_safe
    diagnosis.repair_decision_reason = status.reason
    diagnosis.rule_id = _RULE_BY_SIGNATURE.get(
        status.signature, diagnosis.rule_id
    )
    if status.is_production_safe:
        diagnosis.proposed_action = "Production repair"
    elif status.safety_level is RepairSafetyLevel.EXPERIMENTAL:
        diagnosis.proposed_action = "Experimental - compatibility test only"
    else:
        diagnosis.proposed_action = "Report only"
    diagnosis.decision_trace.append({
        "stage": "viewer_compatibility_policy",
        "signature": status.signature,
        "safety_level": status.safety_level.value,
        "internal_verification": status.internal_verification,
        "corenet_x_viewer": status.corenet_x_viewer.value,
        "production_enabled": status.is_production_safe,
        "reason": status.reason,
    })
    return status


def compatibility_profile_allows(diagnosis: Diagnosis, mode: str) -> bool:
    normalized = mode.strip().casefold()
    signature = repair_signature(diagnosis).casefold()
    if normalized == "compat_shapeaspect_sweptsolid":
        return signature == "shapeaspect/body/sweptsolid"
    if normalized == "compat_shapeaspect_tessellation":
        return signature == "shapeaspect/body/tessellation"
    if normalized == "compat_representationmap_body":
        return signature.startswith("representationmap/body/")
    if normalized == "compat_footprint":
        return signature.startswith("representationmap/footprint/curve2d")
    if normalized == "compat_all":
        return diagnosis.safety_level == RepairSafetyLevel.EXPERIMENTAL.value
    return False
