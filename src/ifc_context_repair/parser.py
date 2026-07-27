from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import DependencyError, InputError, SemanticLoadError, StepSyntaxError


def require_ifcopenshell() -> Any:
    try:
        import ifcopenshell
    except ImportError as exc:
        raise DependencyError(
            "IfcOpenShell is required for semantic IFC inspection. "
            "Install the project dependencies first."
        ) from exc
    return ifcopenshell


def check_step_envelope(path: Path, max_file_size_gb: float | None = None) -> None:
    if not path.is_file():
        raise InputError(f"IFC file does not exist: {path}")
    if path.suffix.lower() != ".ifc":
        raise InputError("Input must have an .ifc extension")
    size = path.stat().st_size
    if max_file_size_gb is not None and size > max_file_size_gb * 1024**3:
        raise InputError(f"Input exceeds configured {max_file_size_gb:g} GiB limit")
    with path.open("rb") as stream:
        head = stream.read(4096).upper()
        if b"ISO-10303-21" not in head or b"HEADER;" not in head:
            raise StepSyntaxError("File does not contain a valid IFC STEP header")
        tail_size = min(size, 8192)
        stream.seek(max(0, size - tail_size))
        tail = stream.read().upper()
        if b"END-ISO-10303-21" not in tail:
            raise StepSyntaxError("IFC STEP termination marker is missing")


def open_model(path: str | Path, max_file_size_gb: float | None = None) -> Any:
    source = Path(path).resolve()
    check_step_envelope(source, max_file_size_gb)
    ifcopenshell = require_ifcopenshell()
    try:
        return ifcopenshell.open(str(source))
    except Exception as exc:
        raise SemanticLoadError(
            f"IfcOpenShell could not parse {source.name}: {exc}"
        ) from exc
