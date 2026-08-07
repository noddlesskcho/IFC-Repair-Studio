from __future__ import annotations

import shutil
from pathlib import Path

from ifc_context_repair.compatibility_outputs import (
    generate_compatibility_test_outputs,
)
from ifc_context_repair.config import RepairConfig
from ifc_context_repair.repair import analyse, repair_file
from tests.fixtures.synthetic_ifc import build_ifc_sg_fixture


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "validation-output" / "repair-safety-v1.0.0"
    validation_root = (root / "validation-output").resolve()
    if not output_dir.resolve().is_relative_to(validation_root):
        raise RuntimeError("Refusing to clean a path outside validation-output")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    source = output_dir / "Synthetic_IFCSG_Viewer_Compatibility.ifc"
    build_ifc_sg_fixture(
        source,
        direct_missing=True,
        shape_aspect_missing=True,
        footprint_map_missing=True,
        type_owned_without_occurrences=True,
        space_without_body=True,
        quantity_review=True,
        georeferencing=True,
    )
    audit = analyse(source, repair_mode="audit")
    production = repair_file(RepairConfig(
        source=source,
        output=output_dir / "Synthetic_IFCSG_PRODUCTION_REPAIRED.ifc",
        repair_mode="production",
        generate_report=True,
    ))
    compatibility = generate_compatibility_test_outputs(RepairConfig(
        source=source,
        output_dir=output_dir / "compatibility-tests",
        repair_mode="production",
        generate_report=True,
    ))
    print(f"Audit HTML: {audit.report_paths.get('html')}")
    print(f"Production output: {production.output}")
    print(f"Production repairs: {production.summary_counts.get('SuccessfullyRepaired', 0)}")
    print(
        "Experimental findings: "
        f"{production.summary_counts.get('ExperimentalFindings', 0)}"
    )
    print(
        "Compatibility matrix: "
        f"{compatibility.report_paths.get('compatibility_matrix_html')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
