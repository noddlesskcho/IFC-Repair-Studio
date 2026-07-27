from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import pytest

from ifc_context_repair.errors import InputError
from ifc_context_repair.file_io import prepare_input
from ifc_context_repair.ifc_sg_assessment import (
    assess_ifc_sg,
    processing_strategy,
    size_category,
)
from ifc_context_repair.models import IfcSgClassification, ProcessingStrategy
from ifc_context_repair.prescan import StepPrescanProfile, profile_step
from ifc_context_repair.rules.ifc_sg import IFC_SG_RULES, IfcSgRuleContext


def minimal_ifc(schema: str = "IFC4") -> bytes:
    return (
        b"ISO-10303-21;\nHEADER;\n"
        b"FILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');\n"
        b"FILE_NAME('x.ifc','',(),(),'Autodesk Revit IFC+SG','Revit','');\n"
        + f"FILE_SCHEMA(('{schema}'));\n".encode()
        + b"ENDSEC;\nDATA;\n"
        b"#1=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#2));\n"
        b"#2=IFCSPACE('g',$,'Space',$,$,$,$,$,$,$,$);\n"
        b"#3=IFCREPRESENTATIONMAP(#4,#1);\n"
        b"#5=IFCPROPERTYSET('g',$,'SGPset_Project',$,());\n"
        b"#6=IFCPROJECTEDCRS('SVY21',$,$,$,$,$,$);\n"
        b"#7=IFCMAPCONVERSION(#8,#6,1.,2.,3.,1.,0.,1.);\n"
        b"ENDSEC;\nEND-ISO-10303-21;\n"
    )


def test_profile_and_ifc_sg_assessment() -> None:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "case.ifc"
        path.write_bytes(minimal_ifc())
        profile = profile_step(path)
    assert profile.schema == "IFC4"
    assert profile.entity_counts["IFCSHAPEREPRESENTATION"] == 1
    assert profile.entity_counts["IFCSPACE"] == 1
    assert profile.missing_context_signatures == {"Body / SweptSolid": 1}
    assessment = assess_ifc_sg(profile)
    assert assessment.classification is IfcSgClassification.LIKELY
    assert assessment.likely_exporter == "Autodesk Revit (version not identified)"


def test_zip_requires_exactly_one_ifc_and_extracts_safely() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        archive_path = root / "model.ifczip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("nested/model.ifc", minimal_ifc())
        with prepare_input(archive_path) as prepared:
            assert prepared.input_kind == "IFCZIP"
            assert prepared.ifc_path.read_bytes() == minimal_ifc()
            extracted = prepared.ifc_path
        assert not extracted.exists()

        invalid = root / "two.zip"
        with zipfile.ZipFile(invalid, "w") as archive:
            archive.writestr("a.ifc", minimal_ifc())
            archive.writestr("b.ifc", minimal_ifc())
        with pytest.raises(InputError, match="exactly one"):
            prepare_input(invalid)


def test_size_and_processing_strategies() -> None:
    assert size_category(99 * 1024**2) == "Small"
    assert size_category(500 * 1024**2) == "Large"
    assert processing_strategy(
        50 * 1024**2, available_memory=8 * 1024**3, schema_supported=True
    ) is ProcessingStrategy.FULL_SEMANTIC
    assert processing_strategy(
        3 * 1024**3, available_memory=2 * 1024**3, schema_supported=True
    ) is ProcessingStrategy.LIMITED_AUDIT
    assert processing_strategy(
        50 * 1024**2, available_memory=8 * 1024**3, schema_supported=False
    ) is ProcessingStrategy.LIMITED_AUDIT


def test_registry_skips_irrelevant_rules() -> None:
    profile = StepPrescanProfile(
        schema="IFC4",
        file_size=10,
        entity_counts={},
        candidates=[],
    )
    selection = IFC_SG_RULES.select(
        IfcSgRuleContext(model=None, schema="IFC4", profile=profile)
    )
    assert "DIRECT_PRODUCT_MISSING_CONTEXT_V2" in selection.skipped
    assert "IFCSPACE_BODY_AUDIT_V1" in selection.skipped
    assert "BASE_QUANTITY_AUDIT_V1" in selection.skipped
    assert any(
        rule.rule_id == "IFCSG_GEOREFERENCING_AUDIT_V1"
        for rule in selection.selected
    )


def test_shape_aspect_map_rule_is_registered_and_bundled() -> None:
    rule_ids = {rule.rule_id for rule in IFC_SG_RULES.all()}
    assert "SHAPE_ASPECT_MAP_MISSING_CONTEXT_V1" in rule_ids

    catalog_path = (
        Path(__file__).parents[2] / "assets" / "rules_ifc_sg.json"
    )
    assert "SHAPE_ASPECT_MAP_MISSING_CONTEXT_V1" in catalog_path.read_text(
        encoding="utf-8"
    )


def test_non_ifc4_is_unsupported() -> None:
    profile = StepPrescanProfile("IFC2X3", 10)
    assessment = assess_ifc_sg(profile)
    assert assessment.classification is IfcSgClassification.UNSUPPORTED
