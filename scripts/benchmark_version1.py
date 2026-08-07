from __future__ import annotations

import argparse
from pathlib import Path

try:
    import ifcopenshell
    if not hasattr(ifcopenshell, "open"):
        raise ImportError
except ImportError:
    from scripts.pyz_runtime import install

    install(Path(__file__).parents[1])

from ifc_context_repair.benchmarking import (
    CONFIGURATIONS,
    benchmark_scan,
    export_results,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("validation-output/version1-benchmark"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--configuration",
        action="append",
        choices=tuple(CONFIGURATIONS),
        help="Run only the named configuration (may be repeated).",
    )
    args = parser.parse_args()
    results = []
    for path in args.files:
        for configuration in (args.configuration or CONFIGURATIONS):
            benchmark_scan(
                path, test_name=path.stem, configuration=configuration, run_number=0
            )
            print(f"Warm-up complete: {path.name} / {configuration}", flush=True)
            for run_number in range(1, args.runs + 1):
                result = benchmark_scan(
                    path,
                    test_name=path.stem,
                    configuration=configuration,
                    run_number=run_number,
                )
                results.append(result)
                print(
                    f"Run {run_number}/{args.runs}: {path.name} / {configuration} "
                    f"{result.total_seconds:.3f}s",
                    flush=True,
                )
    export_results(results, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
