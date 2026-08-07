"""Run the source test suite against dependencies from the prior onedir build."""
from __future__ import annotations

import importlib
import inspect
import re
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path

from scripts.pyz_runtime import install


class _Mark:
    @staticmethod
    def skipif(condition: bool, *, reason: str = ""):
        def decorate(value):  # noqa: ANN001
            value.__unittest_skip__ = bool(condition)
            value.__unittest_skip_why__ = reason
            return value
        return decorate


@contextmanager
def _raises(error_type, match: str | None = None):  # noqa: ANN001
    try:
        yield
    except error_type as error:
        if match and re.search(match, str(error)) is None:
            raise AssertionError(f"{error!s} does not match {match!r}") from error
    else:
        raise AssertionError(f"Expected {error_type.__name__}")


def main() -> int:
    workspace = Path(__file__).parents[1]
    install(workspace)
    pytest_stub = types.ModuleType("pytest")
    pytest_stub.mark = _Mark()
    pytest_stub.raises = _raises
    sys.modules.setdefault("pytest", pytest_stub)
    suite = unittest.defaultTestLoader.discover(str(workspace / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    failures = len(result.failures) + len(result.errors)
    for path in sorted((workspace / "tests").rglob("test_*.py")):
        module_name = ".".join(path.relative_to(workspace).with_suffix("").parts)
        module = importlib.import_module(module_name)
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_") or inspect.signature(function).parameters:
                continue
            if getattr(function, "__unittest_skip__", False):
                print(f"SKIP {module_name}.{name}")
                continue
            try:
                function()
            except Exception as error:
                failures += 1
                print(f"FAIL {module_name}.{name}: {type(error).__name__}: {error}")
            else:
                print(f"PASS {module_name}.{name}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
