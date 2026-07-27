"""Dependency-light regression checks for the July 2026 maintenance fixes."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from ifc_context_repair.config import RepairConfig
from ifc_context_repair.rules.ifc_sg.production import IFC_SG_RULES
from ifc_context_repair.utils import format_bytes


ROOT = Path(__file__).resolve().parents[1]


class _Buttons:
    Yes = 1
    No = 2


class _MessageBox:
    StandardButton = _Buttons
    answer = _Buttons.Yes

    @staticmethod
    def question(*_args: object) -> int:
        return _MessageBox.answer


class _Thread:
    @staticmethod
    def isRunning() -> bool:
        return True


class _Owner:
    thread = _Thread()
    cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Event:
    accepted = False
    ignored = False

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


def _load_function(path: Path, name: str, namespace: dict[str, object]):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    function.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


def main() -> None:
    source_root = ROOT / "src" / "ifc_context_repair"
    all_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
    )
    assert f" {chr(0x00F9)} " not in all_text

    ui_path = source_root / "ui" / "main_window.py"
    close_event = _load_function(
        ui_path,
        "closeEvent",
        {"QCloseEvent": object, "QMessageBox": _MessageBox},
    )
    owner = _Owner()
    keep_open = _Event()
    _MessageBox.answer = _Buttons.Yes
    close_event(owner, keep_open)
    assert owner.cancelled and keep_open.ignored and not keep_open.accepted

    owner = _Owner()
    close_now = _Event()
    _MessageBox.answer = _Buttons.No
    close_event(owner, close_now)
    assert not owner.cancelled and close_now.accepted and not close_now.ignored

    assert "SUPPORTED_INPUT_SUFFIXES" in all_text
    assert "suffix.casefold() in SUPPORTED_INPUT_SUFFIXES" in ui_path.read_text(
        encoding="utf-8"
    )
    ui_tree = ast.parse(ui_path.read_text(encoding="utf-8"))
    enum_node = next(
        node
        for node in ui_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WorkflowState"
    )
    enum_values = {
        statement.targets[0].id: ast.literal_eval(statement.value)
        for statement in enum_node.body
        if isinstance(statement, ast.Assign)
        and isinstance(statement.targets[0], ast.Name)
    }
    assert enum_values["NO_FILE"] != enum_values["READY_TO_SCAN"]
    assert 'self.scan_button.setText("Review IFC")' in ui_path.read_text(
        encoding="utf-8"
    )

    assert RepairConfig.__dataclass_fields__["minimum_confidence"].default == 0.70
    rule_ids = {rule.rule_id for rule in IFC_SG_RULES.all()}
    assert "SHAPE_ASPECT_MAP_MISSING_CONTEXT_V1" in rule_ids
    catalog = json.loads(
        (ROOT / "assets" / "rules_ifc_sg.json").read_text(encoding="utf-8")
    )
    assert "SHAPE_ASPECT_MAP_MISSING_CONTEXT_V1" in {
        rule["rule_id"] for rule in catalog["rules"]
    }
    assert format_bytes(652_954_035) == "622.7 MB"
    print("maintenance-regressions-ok")


if __name__ == "__main__":
    main()
