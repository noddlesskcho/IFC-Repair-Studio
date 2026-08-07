"""Development-only loader for dependencies embedded in the last onedir build.

This is used by source tests on workstations where the packaging interpreter is
not on PATH. It is never imported by the packaged application.
"""
from __future__ import annotations

import importlib.abc
import importlib.util
import marshal
import os
import struct
import sys
import zlib
from pathlib import Path


class PyzFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, archive: Path, native_root: Path) -> None:
        self.archive = archive
        self.native_root = native_root
        with archive.open("rb") as stream:
            if stream.read(4) != b"PYZ\0":
                raise ValueError(f"Not a PYZ archive: {archive}")
            stream.read(4)
            toc_offset = struct.unpack("!i", stream.read(4))[0]
            stream.seek(toc_offset)
            self.toc = dict(marshal.load(stream))

    def find_spec(self, fullname: str, path=None, target=None):  # noqa: ANN001
        supported = ("ifcopenshell", "PySide6", "shiboken6")
        if not any(
            fullname == prefix or fullname.startswith(prefix + ".")
            for prefix in supported
        ):
            return None
        entry = self.toc.get(fullname)
        if entry is None:
            return None
        return importlib.util.spec_from_loader(
            fullname, self, is_package=bool(entry[0])
        )

    def create_module(self, spec):  # noqa: ANN001
        return None

    def exec_module(self, module) -> None:  # noqa: ANN001
        is_package, position, length = self.toc[module.__name__]
        with self.archive.open("rb") as stream:
            stream.seek(position)
            code = marshal.loads(zlib.decompress(stream.read(length)))
        module.__file__ = f"{self.archive}!{module.__name__}"
        if is_package:
            native_package = self.native_root / module.__name__.split(".")[0]
            module.__path__ = [str(native_package)] if native_package.is_dir() else []
            if module.__name__ in {"PySide6", "shiboken6"}:
                module.__file__ = str(native_package / "__init__.py")
        exec(code, module.__dict__)


def install(workspace: Path) -> None:
    build_root = workspace / "build" / "IFCSGRepairAssistant-1.0.0"
    internal = workspace / "dist" / "IFCSGRepairAssistant-1.0.0" / "_internal"
    archive = build_root / "PYZ-00.pyz"
    sys.path.insert(0, str(internal))
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(internal))
        os.add_dll_directory(str(internal / "PySide6"))
        os.add_dll_directory(str(internal / "shiboken6"))
    sys.meta_path.insert(0, PyzFinder(archive, internal))
