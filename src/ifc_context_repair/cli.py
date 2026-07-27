from __future__ import annotations

import argparse
import cProfile
import json
import sys
import time
import tracemalloc
from pathlib import Path

from .comparator import compare_files
from .baseline import analyse_clean_baselines
from .config import RepairConfig
from .errors import DependencyError, InputError, OutputError, ParseError, RepairError
from .file_io import prepare_input
from .naming import default_repaired_path
from .parser import open_model
from .prescan import scan_step
from .repair import analyse, repair_file
from .reporting import write_bundle, write_json
from .validator import validate_schema


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ifc-context-repair")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Prescan and semantically diagnose an IFC")
    scan.add_argument("input", type=Path)
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--prescan-only", action="store_true")
    scan.add_argument(
        "--mode", choices=["safe", "advanced", "audit"], default="safe",
    )
    validate = sub.add_parser("validate", help="Run IFC schema validation")
    validate.add_argument("input", type=Path)
    validate.add_argument("--json", action="store_true")
    repair = sub.add_parser("repair", help="Repair safe missing contexts")
    repair.add_argument("input", type=Path)
    repair.add_argument("--output", type=Path)
    repair.add_argument("--output-dir", type=Path)
    repair.add_argument("--include-warnings", action="store_true")
    repair.add_argument("--geometry-test", action="store_true")
    repair.add_argument(
        "--mode", choices=["safe", "advanced"], default="safe",
    )
    repair.add_argument("--full-validation", action="store_true")
    repair.add_argument("--overwrite-output", action="store_true")
    repair.add_argument("--report", type=Path)
    repair.add_argument(
        "--debug-logging", action="store_true",
        help="Write a developer diagnostic log beside the repaired IFC",
    )
    compare = sub.add_parser("compare", help="Compare clean and faulty IFC semantics")
    compare.add_argument("clean", type=Path)
    compare.add_argument("faulty", type=Path)
    compare.add_argument("--output", type=Path, required=True)
    baseline = sub.add_parser("baseline", help="Analyse one or more known-clean IFC files")
    baseline.add_argument("inputs", nargs="+", type=Path)
    baseline.add_argument("--output", type=Path, required=True)
    bench = sub.add_parser("benchmark", help="Measure stages and peak Python memory")
    bench.add_argument("input", type=Path)
    bench.add_argument("--profile", type=Path)
    bench.add_argument("--quick-scan", action="store_true",
                       help="Benchmark the optimized desktop scan path without full validation")
    return parser


def _scan(args: argparse.Namespace) -> int:
    with prepare_input(args.input) as prepared:
        if args.prescan_only:
            found = scan_step(prepared.ifc_path)
            payload = [vars(c) if hasattr(c, "__dict__") else {
                "step_id": c.step_id, "byte_offset": c.byte_offset,
                "line_number": c.line_number, "record_preview": c.record_preview,
            } for c in found]
            print(json.dumps(payload, indent=2) if args.json else
                  "\n".join(f"#{c.step_id} line {c.line_number} byte {c.byte_offset}" for c in found))
            return 1 if found else 0
        report = analyse(prepared.ifc_path, validate=False, repair_mode=args.mode)
        report.source = str(args.input.resolve())
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for item in report.diagnoses:
            context = f"#{item.proposed_context.step_id}" if item.proposed_context else "none"
            print(f"#{item.representation_step_id}: {item.status.value}; proposed={context}; "
                  f"confidence={item.confidence:.0%}")
            for reason in [*item.evidence, *item.conflicts]:
                print(f"  - {reason}")
    if any(d.status.value == "Ambiguous" for d in report.diagnoses):
        return 3
    return 1 if report.diagnoses else 0


def _validate(args: argparse.Namespace) -> int:
    with prepare_input(args.input) as prepared:
        issues = validate_schema(open_model(prepared.ifc_path))
    payload = [vars(i) if hasattr(i, "__dict__") else {
        "level": i.level, "message": i.message, "entity_step_id": i.entity_step_id,
        "attribute": i.attribute,
    } for i in issues]
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("No validation issues." if not issues else
              "\n".join(f"{i.level}: {i.message}" for i in issues))
    return 2 if any(i.level.lower() == "error" for i in issues) else 0


def _repair(args: argparse.Namespace) -> int:
    with prepare_input(args.input) as prepared:
        output = args.output
        if output is None and args.output_dir is None:
            output = (
                default_repaired_path(args.input.resolve())
                if args.input.suffix.casefold() == ".ifc"
                else args.input.resolve().with_name(
                    f"{args.input.stem}_repaired.ifc"
                )
            )
        config = RepairConfig(
            source=prepared.ifc_path, output=output, output_dir=args.output_dir,
            create_backup=False, replace_original_with_backup=False,
            include_warnings=args.include_warnings,
            geometry_test=args.geometry_test, repair_mode=args.mode,
            full_validation=args.full_validation,
            overwrite_output=args.overwrite_output,
            debug_logging=args.debug_logging,
        )
        report = repair_file(config)
        report.source = str(args.input.resolve())
    if args.report:
        paths = write_bundle(report, args.report)
        print(f"Reports: {', '.join(str(p) for p in paths.values())}")
    print(f"Output: {report.output or 'not written'}")
    if not report.output:
        return 3 if any(d.status.value == "Ambiguous" for d in report.diagnoses) else 1
    return 2 if any(i.level.lower() == "error" for i in report.validation_new) else 0


def _benchmark(args: argparse.Namespace) -> int:
    def run() -> dict[str, object]:
        tracemalloc.start()
        started = time.perf_counter()
        with prepare_input(args.input) as prepared:
            report = analyse(
                prepared.ifc_path,
                validate=not args.quick_scan,
                quick=args.quick_scan,
            )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {"file_size": args.input.stat().st_size, "total_seconds": time.perf_counter() - started,
                "peak_python_bytes": peak, "candidate_count": len(report.prescan_candidates),
                "repairable_count": sum(d.proposed_context is not None for d in report.diagnoses),
                "mode": "quick_scan" if args.quick_scan else "full_validation",
                "durations": report.durations}
    if args.profile:
        profiler = cProfile.Profile()
        result = profiler.runcall(run)
        profiler.dump_stats(args.profile)
    else:
        result = run()
    print(json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "scan": return _scan(args)
        if args.command == "validate": return _validate(args)
        if args.command == "repair": return _repair(args)
        if args.command == "compare":
            write_json(compare_files(args.clean, args.faulty), args.output)
            return 0
        if args.command == "baseline":
            result = analyse_clean_baselines(args.inputs)
            write_json(result, args.output)
            return 0 if result["all_files_clean"] else 2
        if args.command == "benchmark": return _benchmark(args)
    except (InputError, ParseError, DependencyError) as exc:
        print(f"Input error: {exc}", file=sys.stderr); return 4
    except OutputError as exc:
        print(f"Output error: {exc}", file=sys.stderr); return 5
    except RepairError as exc:
        print(f"Repair error: {exc}", file=sys.stderr); return 6
    except Exception as exc:
        print(f"Unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr); return 6
    return 6


if __name__ == "__main__":
    raise SystemExit(main())
