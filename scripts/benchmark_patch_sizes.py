from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

from ifc_context_repair.change_audit import audit_targeted_changes
from ifc_context_repair.step_patch import apply_patch_plan, build_patch_plan, validate_patch_plan
from ifc_context_repair.target_verification import verify_targeted_output
from benchmark_repair import _memory


MIB = 1024 * 1024


def _create_sample(path: Path, size: int) -> None:
    prefix = (
        b"ISO-10303-21;\r\nHEADER;\r\nENDSEC;\r\nDATA;\r\n"
        b"#10=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',());\r\n"
    )
    footer = b"\r\nENDSEC;\r\nEND-ISO-10303-21;\r\n"
    filler = b" " * MIB
    with path.open("wb") as stream:
        stream.write(prefix)
        remaining = size - len(prefix) - len(footer)
        while remaining:
            chunk = filler[: min(remaining, len(filler))]
            stream.write(chunk)
            remaining -= len(chunk)
        stream.write(footer)


def benchmark(size_mb: int) -> dict[str, object]:
    size = size_mb * MIB
    free = shutil.disk_usage(Path.cwd()).free
    required = int(size * 2.2) + 128 * MIB
    if free < required:
        return {
            "size_mb": size_mb, "status": "skipped",
            "reason": f"requires {required:,} free bytes; {free:,} available",
        }
    with tempfile.TemporaryDirectory(prefix=f"ifc-patch-{size_mb}mb-") as folder:
        memory_before = _memory()
        source = Path(folder) / "source.ifc"
        output = Path(folder) / "output.ifc"
        _create_sample(source, size)
        started = time.perf_counter()
        mark = time.perf_counter()
        plan = build_patch_plan(source, {10: 26})
        plan_seconds = time.perf_counter() - mark
        validate_patch_plan(plan)
        written = apply_patch_plan(plan, output)
        mark = time.perf_counter()
        verified = verify_targeted_output(
            output, {10: 26}, source=source, plan=plan, write_result=written,
        )
        verification_seconds = time.perf_counter() - mark
        mark = time.perf_counter()
        audit = audit_targeted_changes(source, output, plan, written)
        audit_seconds = time.perf_counter() - mark
        total = time.perf_counter() - started
        memory_after = _memory()
        return {
            "size_mb": size_mb, "status": "passed", "total_seconds": total,
            "patch_plan_seconds": plan_seconds,
            "output_write_seconds": written.write_seconds,
            "flush_seconds": written.flush_seconds,
            "verification_seconds": verification_seconds,
            "change_audit_seconds": audit_seconds,
            "throughput_bytes_per_second": written.throughput_bytes_per_second,
            "working_set_before_bytes": memory_before[0],
            "working_set_after_bytes": memory_after[0],
            "peak_working_set_bytes": memory_after[1],
            "verified": verified.passed, "change_audit_passed": audit.passed,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[50, 500, 1024])
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    results = [benchmark(size) for size in args.sizes]
    rendered = json.dumps(results, indent=2)
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if all(item["status"] in {"passed", "skipped"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
