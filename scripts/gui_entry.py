import json
import sys
from pathlib import Path


def _run_packaged_self_test(arguments: list[str]) -> int:
    """Exercise the frozen repair stack without starting the GUI.

    This deliberately remains an undocumented diagnostic switch rather than a
    second user workflow. Release engineering uses it to prove that the
    packaged IfcOpenShell, patch writer, verifier and reporters work together.
    """
    if len(arguments) not in {2, 3}:
        return 64
    source = Path(arguments[0]).resolve()
    output = Path(arguments[1]).resolve()
    mode = arguments[2].lower() if len(arguments) == 3 else "safe"
    if mode not in {"safe", "audit"}:
        return 64
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Keep the frozen entry point lightweight and import the repair stack
        # only after the diagnostic arguments have been validated.
        from ifc_context_repair.config import RepairConfig
        from ifc_context_repair.repair import repair_file

        report = repair_file(
            RepairConfig(
                source=source,
                output=output,
                repair_mode=mode,
                overwrite_output=True,
                generate_report=True,
                debug_logging=True,
            )
        )
        result_path = output.with_name(f"{output.stem}_self_test.json")
        result_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        failure_path = output.with_name(f"{output.stem}_self_test_failure.json")
        failure_path.write_text(
            json.dumps(
                {"exception_type": type(exc).__name__, "message": str(exc)},
                indent=2,
            ),
            encoding="utf-8",
        )
        return 1
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        index = sys.argv.index("--self-test")
        raise SystemExit(_run_packaged_self_test(sys.argv[index + 1:]))
    from ifc_context_repair.app import main

    raise SystemExit(main())
