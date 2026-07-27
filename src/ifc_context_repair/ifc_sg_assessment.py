from __future__ import annotations

import shutil
import re
from pathlib import Path
from typing import Any

from .diagnostics import system_snapshot
from .models import (
    FileAssessment,
    IfcSgAssessment,
    IfcSgClassification,
    ProcessingStrategy,
)
from .prescan import StepPrescanProfile


SUPPORTED_SCHEMAS = frozenset({"IFC4"})


def size_category(size: int) -> str:
    if size < 100 * 1024**2:
        return "Small"
    if size < 500 * 1024**2:
        return "Medium"
    if size < 2 * 1024**3:
        return "Large"
    return "Very large"


def processing_strategy(
    size: int,
    *,
    available_memory: int | None,
    schema_supported: bool,
) -> ProcessingStrategy:
    if not schema_supported:
        return ProcessingStrategy.LIMITED_AUDIT
    if size < 100 * 1024**2:
        return ProcessingStrategy.FULL_SEMANTIC
    if size < 500 * 1024**2:
        return ProcessingStrategy.HYBRID
    if size < 2 * 1024**3:
        if available_memory is not None and available_memory < size * 2:
            return ProcessingStrategy.STREAMING_FIRST
        return ProcessingStrategy.HYBRID
    if available_memory is not None and available_memory < size * 2:
        return ProcessingStrategy.LIMITED_AUDIT
    return ProcessingStrategy.STREAMING_FIRST


def _exporter(profile: StepPrescanProfile) -> tuple[str, list[str]]:
    header = profile.exporter_text.casefold()
    if "revit" in header or "autodesk" in header:
        version = re.search(r"\b(2025|2026)\b", header)
        if version:
            product = f"Autodesk Revit {version.group(1)}"
            return product, [f"STEP header identifies {product}"]
        return (
            "Autodesk Revit (version not identified)",
            ["STEP header references Autodesk/Revit, but not version 2025 or 2026"],
        )
    if "archicad" in header or "graphisoft" in header:
        return "Graphisoft Archicad", ["FILE_NAME header references Graphisoft/Archicad"]
    if "tekla" in header or "trimble" in header:
        return "Trimble Tekla", ["FILE_NAME header references Trimble/Tekla"]
    if "openbuildings" in header or "bentley" in header:
        return "Bentley OpenBuildings", ["FILE_NAME header references Bentley/OpenBuildings"]
    if "bricscad" in header:
        return "BricsCAD BIM", ["FILE_NAME header references BricsCAD"]
    return "Unknown", ["No supported authoring tool was identified in the STEP header"]


def assess_ifc_sg(profile: StepPrescanProfile, model: Any | None = None) -> IfcSgAssessment:
    schema = (profile.schema or "").upper()
    exporter, exporter_evidence = _exporter(profile)
    evidence: list[str] = []
    warnings: list[str] = []
    score = 0
    if schema == "IFC4":
        score += 2
        evidence.append("FILE_SCHEMA is IFC4, the supported IFC+SG workflow schema")
    else:
        return IfcSgAssessment(
            IfcSgClassification.UNSUPPORTED,
            evidence=[f"FILE_SCHEMA is {schema or 'unknown'}"],
            warnings=[
                f"This file uses {schema or 'an unknown schema'}. The current repair "
                "rules are designed and tested for IFC+SG IFC4 files. No repair may be applied."
            ],
            likely_exporter=exporter,
            exporter_evidence=exporter_evidence,
            score=score,
        )
    if profile.has_sg_psets:
        score += 5
        evidence.append("SGPset_ or IFC+SG naming was found in the STEP data")
    if exporter in {"Autodesk Revit 2025", "Autodesk Revit 2026"}:
        score += 1
        evidence.append("Exporter pattern is consistent with a priority IFC+SG workflow")
    if profile.entity_counts.get("IFCPROJECTEDCRS", 0):
        score += 1
        evidence.append("IfcProjectedCRS is present")
    if profile.entity_counts.get("IFCMAPCONVERSION", 0):
        score += 1
        evidence.append("IfcMapConversion is present")

    # A semantic check is deliberately supporting evidence, not a hard gate.
    if model is not None:
        try:
            sg_property_sets = sum(
                str(getattr(pset, "Name", "") or "").casefold().startswith("sgpset_")
                for pset in model.by_type("IfcPropertySet")
            )
            if sg_property_sets:
                score += 3
                evidence.append(
                    f"{sg_property_sets:,} SGPset_ property set(s) were confirmed semantically"
                )
        except Exception as exc:
            warnings.append(f"Semantic IFC+SG evidence check was unavailable: {exc}")

    if score >= 6:
        classification = IfcSgClassification.LIKELY
    elif score >= 3:
        classification = IfcSgClassification.POSSIBLE
    else:
        classification = IfcSgClassification.NOT_IDENTIFIABLE
        warnings.append(
            "This file could not be confidently identified as an IFC+SG export. "
            "Repair rules may not be applicable. Audit Only is recommended."
        )
    return IfcSgAssessment(
        classification,
        evidence=evidence,
        warnings=warnings,
        likely_exporter=exporter,
        exporter_evidence=exporter_evidence,
        score=score,
    )


def build_file_assessment(
    source: Path,
    profile: StepPrescanProfile,
    *,
    original_name: str | None = None,
    input_kind: str = "IFC",
    model: Any | None = None,
) -> FileAssessment:
    snapshot = system_snapshot(source.parent)
    available_memory = snapshot.get("system_available_memory_bytes")
    free_disk = shutil.disk_usage(source.parent).free
    assessment = assess_ifc_sg(profile, model)
    return FileAssessment(
        original_name=original_name or source.name,
        working_name=source.name,
        input_kind=input_kind,
        schema=profile.schema,
        size_bytes=profile.file_size,
        size_category=size_category(profile.file_size),
        strategy=processing_strategy(
            profile.file_size,
            available_memory=available_memory,
            schema_supported=(profile.schema or "").upper() in SUPPORTED_SCHEMAS,
        ),
        available_memory_bytes=available_memory,
        available_disk_bytes=free_disk,
        estimated_output_bytes=int(profile.file_size * 1.02),
        ifc_sg=assessment,
        prescan_counts={
            **profile.entity_counts,
            "MISSING_CONTEXTS": len(profile.candidates),
        },
    )
