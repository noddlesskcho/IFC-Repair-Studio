from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import ArchiveError, InputError


SUPPORTED_INPUT_SUFFIXES = frozenset({".ifc", ".ifczip", ".zip"})


@dataclass(slots=True)
class PreparedInput:
    original: Path
    ifc_path: Path
    input_kind: str
    _temporary_directory: Path | None = None

    def cleanup(self) -> None:
        if self._temporary_directory and self._temporary_directory.is_dir():
            shutil.rmtree(self._temporary_directory, ignore_errors=True)
            self._temporary_directory = None

    def __enter__(self) -> "PreparedInput":
        return self

    def __exit__(self, *_args: object) -> None:
        self.cleanup()


def _validated_ifc_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    members = [
        item for item in archive.infolist()
        if not item.is_dir() and PurePosixPath(item.filename).suffix.casefold() == ".ifc"
    ]
    if len(members) != 1:
        raise ArchiveError(
            f"Archive must contain exactly one IFC file; found {len(members)}."
        )
    member = members[0]
    path = PurePosixPath(member.filename)
    if path.is_absolute() or ".." in path.parts:
        raise ArchiveError("Archive contains an unsafe IFC path")
    if member.file_size <= 0:
        raise ArchiveError("The IFC contained in the archive is empty")
    return member


def prepare_input(path: str | Path) -> PreparedInput:
    source = Path(path).resolve()
    if not source.is_file():
        raise InputError(f"Input file does not exist: {source}")
    suffix = source.suffix.casefold()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise InputError("Select an .ifc, .ifczip, or .zip file containing one IFC")
    if suffix == ".ifc":
        return PreparedInput(source, source, "IFC")
    try:
        archive = zipfile.ZipFile(source, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveError(f"Archive could not be opened: {exc}") from exc
    temp_root: Path | None = None
    try:
        member = _validated_ifc_member(archive)
        temp_root = Path(tempfile.mkdtemp(prefix="ifc-repair-studio-"))
        extracted = temp_root / Path(PurePosixPath(member.filename).name)
        with archive.open(member, "r") as input_stream, extracted.open("xb") as output:
            shutil.copyfileobj(input_stream, output, length=8 * 1024 * 1024)
        return PreparedInput(
            source,
            extracted,
            "IFCZIP" if suffix == ".ifczip" else "ZIP",
            temp_root,
        )
    except Exception:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)
        raise
    finally:
        archive.close()
