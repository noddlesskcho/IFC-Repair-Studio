from __future__ import annotations

import re
import traceback
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QMenu, QRadioButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..config import RepairConfig
from ..errors import CancelledError
from ..models import RunReport, Status
from ..naming import default_repaired_path, overwrite_backup_path
from ..output_safety import cleanup_abandoned_temps
from ..repair import analyse, repair_file
from ..rules import ACTIVE_RULE
from ..telemetry import StageUpdate
from ..workers import CancellationToken


LIGHT_STYLE = """
QMainWindow, QWidget#root, QScrollArea#scroll { background:#f5f7fa; color:#172033; }
QFrame#card { background:#ffffff; border:1px solid #dce3ec; border-radius:9px; }
QFrame#successCard { background:#f0faf3; border:1px solid #a9dfb5; border-radius:9px; }
QFrame#errorCard { background:#fff5f5; border:1px solid #efb2b2; border-radius:9px; }
QLabel#muted { color:#657286; }
QLabel#title { font-size:24px; font-weight:700; color:#111827; }
QLabel#section { font-size:13px; font-weight:700; color:#253247; }
QLabel#status { padding:5px 11px; border-radius:12px; background:#eaf2ff; color:#155eef; font-weight:600; }
QLabel#stageActive { color:#155eef; font-weight:700; }
QLabel#stageDone { color:#22863a; font-weight:700; }
QLabel#stagePending { color:#7b8798; }
QLabel#metricValue { font-size:20px; font-weight:700; color:#111827; }
QLabel#metricLabel { color:#5d697b; font-size:11px; }
QPushButton { min-height:20px; border:1px solid #cfd8e5; border-radius:6px; background:#fff; color:#263246; padding:8px 14px; }
QPushButton:hover { background:#f2f5f9; border-color:#9eacc0; }
QPushButton:focus { border:2px solid #4c8dff; padding:7px 13px; }
QPushButton:disabled { color:#9da7b5; background:#edf0f4; border-color:#e1e5eb; }
QPushButton#primary { color:#fff; background:#155eef; border-color:#155eef; font-weight:700; }
QPushButton#primary:hover { background:#0b4fd4; }
QPushButton#quiet { background:transparent; border-color:transparent; color:#526176; }
QLineEdit { border:1px solid #cfd8e5; border-radius:6px; background:#fff; padding:8px; selection-background-color:#155eef; }
QLineEdit:focus { border:2px solid #4c8dff; padding:7px; }
QProgressBar { border:0; border-radius:4px; background:#e5eaf1; min-height:8px; max-height:8px; }
QProgressBar::chunk { border-radius:4px; background:#238636; }
QRadioButton, QCheckBox { spacing:8px; }
"""

class WorkflowState(Enum):
    NO_FILE = "No file"
    READY_TO_SCAN = "Ready to scan"
    SCANNING = "Scanning"
    ISSUES_FOUND = "Issues found"
    NO_ISSUES = "No issues"
    REPAIRING = "Repairing"
    COMPLETED = "Completed"
    FAILED = "Attention required"


@dataclass(slots=True)
class FileMetadata:
    path: Path
    size: int
    modified: datetime
    schema: str | None


class TaskWorker(QObject):
    stage_changed = Signal(object)
    completed = Signal(object)
    failed = Signal(object)
    cancelled = Signal(object)

    def __init__(self, function: Callable[[Callable[[StageUpdate], None]], RunReport]) -> None:
        super().__init__()
        self.function = function
        self.last_stage = StageUpdate("starting", "Starting")

    @Slot()
    def run(self) -> None:
        def telemetry(update: StageUpdate) -> None:
            self.last_stage = update
            self.stage_changed.emit(update)

        try:
            self.completed.emit(self.function(telemetry))
        except CancelledError as exc:
            context = dict(getattr(exc, "repair_context", {}))
            temporary = context.get("temporary_output_path")
            context.update({
                "message": str(exc), "stage": self.last_stage.stage_id,
                "type": type(exc).__name__, "traceback": traceback.format_exc(),
                "temporary_file_removed": not temporary or not Path(temporary).exists(),
            })
            self.cancelled.emit(context)
        except Exception as exc:
            context = dict(getattr(exc, "repair_context", {}))
            temporary = context.get("temporary_output_path")
            context.update({
                "type": type(exc).__name__, "message": str(exc),
                "stage": self.last_stage.stage_id,
                "traceback": traceback.format_exc(),
                "temporary_file_removed": not temporary or not Path(temporary).exists(),
            })
            self.failed.emit(context)


class Metric(QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 3, 6, 3)
        layout.setSpacing(1)
        self.value = QLabel("0")
        self.value.setObjectName("metricValue")
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        caption.setWordWrap(True)
        layout.addWidget(self.value)
        layout.addWidget(caption)

    def set_value(self, value: int | str) -> None:
        self.value.setText(f"{value:,}" if isinstance(value, int) else str(value))


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value:,} B"


def _read_schema(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            header = stream.read(512 * 1024)
        match = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", header, re.I)
        return match.group(1).decode("ascii", "replace") if match else None
    except OSError:
        return None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IFC Repair Studio")
        self.resize(1080, 850)
        self.setMinimumSize(880, 680)
        self.setAcceptDrops(True)
        self.settings = QSettings("BCA", "IFCRepairStudio")
        recent_directory = self.settings.value("last_output_directory", "")
        if recent_directory:
            cleanup_abandoned_temps(Path(str(recent_directory)), older_than_hours=24.0)
        self.state = WorkflowState.NO_FILE
        self.source_path: Path | None = None
        self.metadata: FileMetadata | None = None
        self.report: RunReport | None = None
        self.report_path: Path | None = None
        self.thread: QThread | None = None
        self.worker: TaskWorker | None = None
        self.token = CancellationToken()
        self.operation = ""
        self.current_stage: StageUpdate | None = None
        self.started_at: datetime | None = None
        self.temporary_path: Path | None = None
        self._build()
        self.setStyleSheet(LIGHT_STYLE)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._update_elapsed)
        self._apply_state(WorkflowState.NO_FILE)

    @staticmethod
    def _card(name: str = "card") -> QFrame:
        frame = QFrame()
        frame.setObjectName(name)
        return frame

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("IFC Repair Studio")
        title.setObjectName("title")
        subtitle = QLabel("Detect, repair and verify targeted IFC representation issues.")
        subtitle.setObjectName("muted")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        self.status_badge = QLabel("Ready")
        self.status_badge.setObjectName("status")
        header.addLayout(titles, 1)
        header.addWidget(self.status_badge)
        layout.addLayout(header)

        rule_row = QHBoxLayout()
        rule_label = QLabel("Active repair rule")
        rule_label.setObjectName("muted")
        rule_name = QLabel(ACTIVE_RULE.display_name)
        rule_name.setObjectName("section")
        rule_name.setToolTip(ACTIVE_RULE.description)
        rule_row.addWidget(rule_label)
        rule_row.addWidget(rule_name)
        rule_row.addStretch(1)
        layout.addLayout(rule_row)

        stages = self._card()
        stage_layout = QHBoxLayout(stages)
        stage_layout.setContentsMargins(16, 10, 16, 10)
        self.stage_labels = []
        for index, text in enumerate(("1  Select File", "2  Scan", "3  Repair and Verify")):
            label = QLabel(text)
            label.setObjectName("stagePending")
            self.stage_labels.append(label)
            stage_layout.addWidget(label)
            if index < 2:
                divider = QLabel("----------------")
                divider.setObjectName("muted")
                stage_layout.addWidget(divider, 1)
        layout.addWidget(stages)

        layout.addWidget(self._build_file_card())
        self.results_card = self._build_results_card()
        layout.addWidget(self.results_card)
        self.action_message = QLabel("")
        self.action_message.setWordWrap(True)
        self.action_message.setStyleSheet("font-size:14px;font-weight:600;")
        layout.addWidget(self.action_message)
        self.output_card = self._build_output_card()
        layout.addWidget(self.output_card)
        layout.addWidget(self._build_action_row())
        self.progress_card = self._build_progress_card()
        layout.addWidget(self.progress_card)
        self.completion_card = self._build_completion_card()
        layout.addWidget(self.completion_card)
        layout.addWidget(self._build_details_card())
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.setCentralWidget(root)

    def _build_file_card(self) -> QFrame:
        card = self._card()
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 13, 16, 13)
        heading = QLabel("File")
        heading.setObjectName("section")
        self.file_name = QLabel("No IFC file selected")
        self.file_name.setStyleSheet("font-weight:700;")
        self.file_meta = QLabel("Select an IFC file to begin")
        self.file_meta.setObjectName("muted")
        self.file_meta.setWordWrap(True)
        self.file_path = QLabel("")
        self.file_path.setObjectName("muted")
        self.file_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.file_path.setWordWrap(True)
        self.select_button = QPushButton("Select IFC File")
        self.select_button.setObjectName("primary")
        self.select_button.setAccessibleName("Select IFC file")
        self.select_button.clicked.connect(self._choose_source)
        layout.addWidget(heading, 0, 0)
        layout.addWidget(self.select_button, 0, 2, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.file_name, 1, 0, 1, 2)
        layout.addWidget(self.file_meta, 2, 0, 1, 3)
        layout.addWidget(self.file_path, 3, 0, 1, 3)
        layout.setColumnStretch(1, 1)
        return card

    def _build_results_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        heading = QLabel("Scan Results")
        heading.setObjectName("section")
        layout.addWidget(heading)
        grid = QGridLayout()
        labels = [
            "Elements Scanned", "Elements Affected", "Representations Scanned",
            "Targeted Issues", "Automatically Repairable",
            "Not Automatically Repairable", "Successfully Repaired",
            "Issues Remaining",
        ]
        self.metrics: dict[str, Metric] = {}
        for index, label in enumerate(labels):
            metric = Metric(label)
            self.metrics[label] = metric
            grid.addWidget(metric, index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        self.breakdown = QLabel("")
        self.breakdown.setObjectName("muted")
        layout.addWidget(self.breakdown)
        return card

    def _build_output_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        heading = QLabel("Output")
        heading.setObjectName("section")
        layout.addWidget(heading)
        self.save_as_radio = QRadioButton("Save as a new repaired file (recommended)")
        self.replace_radio = QRadioButton("Replace original file (advanced)")
        modes = QButtonGroup(self)
        modes.addButton(self.save_as_radio)
        modes.addButton(self.replace_radio)
        self.save_as_radio.setChecked(True)
        self.save_as_radio.toggled.connect(self._output_mode_changed)
        layout.addWidget(self.save_as_radio)
        layout.addWidget(self.replace_radio)
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setAccessibleName("Repaired IFC output path")
        self.browse_output_button = QPushButton("Browse")
        self.browse_output_button.clicked.connect(self._browse_output)
        row.addWidget(self.output_edit, 1)
        row.addWidget(self.browse_output_button)
        layout.addLayout(row)
        self.output_note = QLabel("Original file will remain unchanged")
        self.output_note.setObjectName("muted")
        layout.addWidget(self.output_note)
        self.full_validation = QCheckBox("Run full IFC schema validation")
        self.full_validation.setToolTip(
            "Optional. Full validation can take significantly longer for large models."
        )
        self.full_validation.setChecked(
            self.settings.value("full_validation", False, type=bool)
        )
        layout.addWidget(self.full_validation)
        return card

    def _build_action_row(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scan_button = QPushButton("Scan IFC")
        self.scan_button.clicked.connect(self.scan)
        self.repair_button = QPushButton("Repair")
        self.repair_button.clicked.connect(self.repair)
        layout.addStretch(1)
        layout.addWidget(self.scan_button)
        layout.addWidget(self.repair_button)
        return widget

    def _build_progress_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        top = QHBoxLayout()
        self.progress_stage = QLabel("Waiting")
        self.progress_stage.setObjectName("section")
        self.elapsed_label = QLabel("Elapsed 00:00")
        self.elapsed_label.setObjectName("muted")
        top.addWidget(self.progress_stage)
        top.addStretch(1)
        top.addWidget(self.elapsed_label)
        layout.addLayout(top)
        self.progress_detail = QLabel("")
        self.progress_detail.setObjectName("muted")
        self.progress_detail.setWordWrap(True)
        layout.addWidget(self.progress_detail)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        bottom.addWidget(self.cancel_button)
        layout.addLayout(bottom)
        return card

    def _build_completion_card(self) -> QFrame:
        card = self._card("successCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 13, 16, 13)
        self.completion_title = QLabel("Repair completed successfully")
        self.completion_title.setStyleSheet("font-size:17px;font-weight:700;")
        self.completion_summary = QLabel("")
        self.completion_summary.setWordWrap(True)
        layout.addWidget(self.completion_title)
        layout.addWidget(self.completion_summary)
        buttons = QHBoxLayout()
        self.report_button = QPushButton("Open Report")
        self.report_button.setObjectName("primary")
        self.report_menu = QMenu(self.report_button)
        self.html_report_action = QAction("HTML Engineering Report", self)
        self.pdf_report_action = QAction("PDF Executive Report", self)
        self.repaired_ifc_action = QAction("Open Repaired IFC", self)
        self.html_report_action.triggered.connect(
            lambda: self.open_report("html")
        )
        self.pdf_report_action.triggered.connect(
            lambda: self.open_report("pdf")
        )
        self.repaired_ifc_action.triggered.connect(self.open_repaired_ifc)
        self.report_menu.addAction(self.html_report_action)
        self.report_menu.addAction(self.pdf_report_action)
        self.report_menu.addSeparator()
        self.report_menu.addAction(self.repaired_ifc_action)
        self.report_button.setMenu(self.report_menu)
        self.another_button = QPushButton("Repair Another File")
        self.another_button.clicked.connect(self.reset)
        buttons.addWidget(self.report_button)
        buttons.addWidget(self.another_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return card

    def _build_details_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 10)
        self.details_button = QPushButton("Technical Details")
        self.details_button.setObjectName("quiet")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details)
        self.details_text = QLabel("")
        self.details_text.setObjectName("muted")
        self.details_text.setWordWrap(True)
        self.details_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.details_text.setVisible(False)
        layout.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.details_text)
        return card

    def _set_primary(self, button: QPushButton | None) -> None:
        for candidate in (self.select_button, self.scan_button, self.repair_button):
            candidate.setObjectName("primary" if candidate is button else "")
            candidate.style().unpolish(candidate)
            candidate.style().polish(candidate)

    def _apply_state(self, state: WorkflowState) -> None:
        self.state = state
        self.status_badge.setText(state.value)
        busy = state in {WorkflowState.SCANNING, WorkflowState.REPAIRING}
        self.select_button.setEnabled(not busy)
        self.results_card.setVisible(state not in {WorkflowState.NO_FILE, WorkflowState.READY_TO_SCAN})
        self.output_card.setVisible(state == WorkflowState.ISSUES_FOUND)
        self.progress_card.setVisible(busy)
        self.completion_card.setVisible(state in {WorkflowState.COMPLETED, WorkflowState.FAILED})
        self.scan_button.setVisible(state not in {WorkflowState.NO_FILE, WorkflowState.COMPLETED})
        self.repair_button.setVisible(state in {WorkflowState.ISSUES_FOUND, WorkflowState.REPAIRING})
        self.cancel_button.setVisible(busy)

        if state == WorkflowState.NO_FILE:
            self._set_primary(self.select_button)
            self.select_button.setText("Select IFC File")
            self.scan_button.setEnabled(False)
            self.repair_button.setEnabled(False)
            self.action_message.setText("Select an IFC file to begin.")
            stage = 0
        elif state == WorkflowState.READY_TO_SCAN:
            self._set_primary(self.scan_button)
            self.select_button.setText("Change File")
            self.scan_button.setText("Scan IFC")
            self.scan_button.setEnabled(True)
            self.repair_button.setEnabled(False)
            self.action_message.setText("The file is ready for the active repair rule scan.")
            stage = 1
        elif state == WorkflowState.SCANNING:
            self._set_primary(None)
            self.scan_button.setText("Scanning...")
            self.scan_button.setEnabled(False)
            self.repair_button.setEnabled(False)
            self.action_message.setText("Scanning the selected repair-rule scope.")
            stage = 1
        elif state == WorkflowState.ISSUES_FOUND:
            repairable = self.report.summary_counts.get("AutomaticallyRepairable", 0) if self.report else 0
            affected = self.report.summary_counts.get("ElementsAffected", 0) if self.report else 0
            self._set_primary(self.repair_button)
            self.scan_button.setText("Scan Again")
            self.scan_button.setEnabled(True)
            self.repair_button.setText(f"Repair {repairable:,} Representations")
            self.repair_button.setEnabled(repairable > 0)
            self.action_message.setText(
                f"{repairable:,} repairable representation-context issues were found "
                f"across {affected:,} elements."
            )
            stage = 2
        elif state == WorkflowState.NO_ISSUES:
            self._set_primary(self.select_button)
            self.select_button.setText("Select Another File")
            self.scan_button.setText("Scan Again")
            self.scan_button.setEnabled(True)
            self.repair_button.setEnabled(False)
            self.action_message.setText("No targeted representation-context issues were found.")
            stage = 2
        elif state == WorkflowState.REPAIRING:
            self._set_primary(None)
            self.scan_button.setEnabled(False)
            self.repair_button.setText("Repairing...")
            self.repair_button.setEnabled(False)
            self.action_message.setText("Repair and verification are in progress.")
            stage = 2
        elif state == WorkflowState.COMPLETED:
            self._set_primary(None)
            self.action_message.setText("")
            self.completion_card.setObjectName("successCard")
            self.completion_title.setText("Repair completed successfully")
            stage = 3
        else:
            self._set_primary(None)
            self.completion_card.setObjectName("errorCard")
            self.completion_title.setText("Repair could not be completed")
            stage = 2

        for index, label in enumerate(self.stage_labels):
            label.setObjectName(
                "stageDone" if index < stage else
                "stageActive" if index == min(stage, 2) else "stagePending"
            )
            label.style().unpolish(label)
            label.style().polish(label)

    @Slot()
    def _choose_source(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self, "Select IFC File", "", "IFC files (*.ifc)"
        )
        if value:
            self._set_source(Path(value))

    def _set_source(self, path: Path) -> None:
        if not path.is_file() or path.suffix.casefold() != ".ifc":
            QMessageBox.warning(self, "Invalid IFC", "Select a readable .ifc file.")
            return
        stat = path.stat()
        self.source_path = path.resolve()
        self.metadata = FileMetadata(
            self.source_path, stat.st_size,
            datetime.fromtimestamp(stat.st_mtime), _read_schema(path),
        )
        self.report = None
        self.report_path = None
        self.file_name.setText(path.name)
        schema = self.metadata.schema or "Schema not read yet"
        self.file_meta.setText(
            f"{_format_bytes(stat.st_size)}  |  {schema}  |  Modified "
            f"{self.metadata.modified:%d %b %Y, %I:%M %p}"
        )
        self.file_path.setText(str(self.source_path))
        self.output_edit.setText(str(default_repaired_path(self.source_path)))
        self._clear_metrics()
        self._apply_state(WorkflowState.READY_TO_SCAN)

    def _clear_metrics(self) -> None:
        for metric in self.metrics.values():
            metric.set_value(0)
        self.breakdown.setText("")

    def _output_mode_changed(self, save_as: bool) -> None:
        if not self.source_path:
            return
        if save_as:
            self.output_edit.setText(str(default_repaired_path(self.source_path)))
            self.output_edit.setEnabled(True)
            self.browse_output_button.setEnabled(True)
            self.output_note.setText("Original file will remain unchanged")
        else:
            backup = overwrite_backup_path(self.source_path)
            self.output_edit.setText(str(self.source_path))
            self.output_edit.setEnabled(False)
            self.browse_output_button.setEnabled(False)
            self.output_note.setText(f"Backup will be created as: {backup.name}")

    @Slot()
    def _browse_output(self) -> None:
        if not self.source_path:
            return
        value, _ = QFileDialog.getSaveFileName(
            self, "Save Repaired IFC As", self.output_edit.text(), "IFC files (*.ifc)"
        )
        if value:
            path = Path(value)
            if path.suffix.casefold() != ".ifc":
                path = path.with_suffix(".ifc")
            self.output_edit.setText(str(path))

    def _start_job(
        self, operation: str,
        function: Callable[[Callable[[StageUpdate], None]], RunReport],
    ) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.operation = operation
        self.token = CancellationToken()
        self.started_at = datetime.now()
        self.temporary_path = None
        self.elapsed_timer.start()
        self.progress.setRange(0, 0)
        self.progress_detail.setText("Starting...")
        self._apply_state(
            WorkflowState.SCANNING if operation == "scan" else WorkflowState.REPAIRING
        )
        self.thread = QThread(self)
        self.worker = TaskWorker(function)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.stage_changed.connect(self._stage_changed)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()

    @Slot()
    def scan(self) -> None:
        if not self.source_path:
            return
        path = self.source_path

        def operation(telemetry: Callable[[StageUpdate], None]) -> RunReport:
            report = analyse(
                path, validate=False, quick=True,
                cancelled=self.token.cancelled, telemetry=telemetry,
            )
            return report

        self._start_job("scan", operation)

    @Slot()
    def repair(self) -> None:
        if not self.source_path or not self.report:
            return
        save_as = self.save_as_radio.isChecked()
        output = Path(self.output_edit.text()).expanduser().resolve()
        if save_as and output == self.source_path:
            QMessageBox.warning(
                self, "Choose a new output", "Save As output must differ from the original."
            )
            return
        if save_as and output.exists():
            QMessageBox.warning(
                self, "Output already exists",
                "Choose a different output filename. Existing files are not overwritten in recommended mode.",
            )
            return
        if not save_as:
            backup = overwrite_backup_path(self.source_path)
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Replace original IFC?")
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setText("Replace original IFC?")
            dialog.setInformativeText(
                f"Original:\n{self.source_path.name}\n\nBackup:\n{backup.name}\n\n"
                "The repaired model will replace the original filename."
            )
            replace_button = dialog.addButton(
                "Replace and Repair", QMessageBox.ButtonRole.AcceptRole
            )
            dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            dialog.exec()
            if dialog.clickedButton() is not replace_button:
                return

        self.settings.setValue("full_validation", self.full_validation.isChecked())
        self.settings.setValue("last_output_directory", str(output.parent))
        config = RepairConfig(
            source=self.source_path,
            output=None if not save_as else output,
            create_backup=not save_as,
            replace_original_with_backup=not save_as,
            full_validation=self.full_validation.isChecked(),
            repair_mode="targeted",
        )
        self._start_job(
            "repair", lambda telemetry: repair_file(
                config, cancelled=self.token.cancelled, telemetry=telemetry
            ),
        )

    @Slot(object)
    def _stage_changed(self, update: StageUpdate) -> None:
        self.current_stage = update
        self.progress_stage.setText(update.message)
        self.cancel_button.setEnabled(update.cancellable)
        self.cancel_button.setText("Cancel" if update.cancellable else "Stop After Current Stage")
        if update.bytes_processed is not None and update.bytes_total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(1000, int(update.bytes_processed * 1000 / update.bytes_total)))
            detail = (
                f"{_format_bytes(update.bytes_processed)} of {_format_bytes(update.bytes_total)}  |  "
                f"{update.bytes_processed * 100 / update.bytes_total:.0f}%"
            )
            if update.throughput_bytes_per_second is not None:
                detail += f"  |  {_format_bytes(int(update.throughput_bytes_per_second))}/s"
            if update.elapsed_seconds is not None:
                detail += f"  |  Elapsed {int(update.elapsed_seconds)//60:02d}:{int(update.elapsed_seconds)%60:02d}"
            if update.estimated_remaining_seconds is not None:
                remaining = max(0, int(update.estimated_remaining_seconds))
                detail += f"  |  Remaining {remaining//60:02d}:{remaining%60:02d}"
            if update.current is not None and update.total:
                detail += f"  |  Changes {update.current:,}/{update.total:,}"
        elif update.current is not None and update.total:
            self.progress.setRange(0, update.total)
            self.progress.setValue(update.current)
            detail = f"{update.current:,} of {update.total:,}"
        else:
            self.progress.setRange(0, 0)
            detail = "This stage may take several minutes for large IFC files."
        if update.temporary_path:
            self.temporary_path = update.temporary_path
        if update.output_size is not None:
            detail += f"  |  Temporary output: {_format_bytes(update.output_size)}"
        self.progress_detail.setText(detail)

    @Slot(object)
    def _completed(self, report: RunReport) -> None:
        self.elapsed_timer.stop()
        self.report = report
        self.temporary_path = None
        if self.operation == "scan":
            self._show_scan_results(report)
            if report.diagnoses:
                self._apply_state(WorkflowState.ISSUES_FOUND)
            else:
                self._apply_state(WorkflowState.NO_ISSUES)
            return

        self._show_scan_results(report)
        html = report.report_paths.get("html")
        self.report_path = Path(html) if html else None
        repaired = report.summary_counts.get("SuccessfullyRepaired", 0)
        affected = report.summary_counts.get("ElementsAffected", 0)
        remaining = report.summary_counts.get("TargetedIssuesRemaining", 0)
        verification = "Passed" if report.targeted_verification.get("passed") else "Not passed"
        duration = sum(report.durations.values())
        self.completion_summary.setText(
            f"{repaired:,} representations repaired across {affected:,} elements\n"
            f"{remaining:,} targeted issues remaining  |  Verification: {verification}\n"
            f"Original: {report.source}\nRepaired: {report.output}\n"
            f"Backup: {report.backup or 'Not required - original unchanged'}\n"
            f"Output size: {_format_bytes(report.output_size)}  |  Duration: {duration:.1f} seconds"
        )
        self.html_report_action.setEnabled(bool(report.report_paths.get("html")))
        self.pdf_report_action.setEnabled(bool(report.report_paths.get("pdf")))
        self.repaired_ifc_action.setEnabled(bool(report.output))
        self.report_button.setEnabled(any((
            self.html_report_action.isEnabled(), self.pdf_report_action.isEnabled(),
            self.repaired_ifc_action.isEnabled(),
        )))
        self.details_text.setText(self._technical_details(report))
        self._apply_state(WorkflowState.COMPLETED)

    def _show_scan_results(self, report: RunReport) -> None:
        counts = report.summary_counts
        values = {
            "Elements Scanned": counts.get("ElementsScanned", 0),
            "Elements Affected": counts.get("ElementsAffected", 0),
            "Representations Scanned": counts.get("RepresentationsScanned", 0),
            "Targeted Issues": counts.get("AffectedRepresentations", 0),
            "Automatically Repairable": counts.get("AutomaticallyRepairable", 0),
            "Not Automatically Repairable": counts.get("NotAutomaticallyRepairable", 0),
            "Successfully Repaired": counts.get("SuccessfullyRepaired", 0),
            "Issues Remaining": counts.get("TargetedIssuesRemaining", 0),
        }
        for key, value in values.items():
            self.metrics[key].set_value(value)
        groups = Counter(
            (item.representation_identifier or "Unidentified",
             item.representation_type or "Unspecified")
            for item in report.diagnoses
        )
        self.breakdown.setText("  |  ".join(
            f"{identifier} / {kind}: {count:,}"
            for (identifier, kind), count in sorted(groups.items())
        ))
        self.details_text.setText(self._technical_details(report))

    @staticmethod
    def _technical_details(report: RunReport) -> str:
        timings = "\n".join(
            f"{key.replace('_', ' ').title()}: {value:.3f} seconds"
            for key, value in report.durations.items()
        )
        return (
            f"Rule: {report.active_rule_id} v{report.active_rule_version}\n"
            f"Schema: {report.schema}\nInput: {report.source}\n"
            f"Output: {report.output or 'Not written'}\n"
            f"Diagnostic log: {report.log_path or 'Not created'}\n\n{timings}"
        )

    @Slot(object)
    def _failed(self, details: dict[str, str]) -> None:
        self.elapsed_timer.stop()
        source_status = (
            "The original IFC was not changed."
            if self.save_as_radio.isChecked()
            else "Check the backup path before retrying."
        )
        self.completion_summary.setText(
            f"Failed stage: {details.get('stage', 'unknown')}\n"
            f"{details.get('type', 'Error')}: {details.get('message', 'Unknown error')}\n"
            f"{source_status}\n"
            f"Temporary output removed: {details.get('temporary_file_removed', True)}\n"
            f"Output: {details.get('final_output_path', self.output_edit.text())}\n"
            f"Debug log: {details.get('log_path') or 'Not enabled'}"
        )
        self.report_button.setEnabled(False)
        self._apply_state(WorkflowState.FAILED)

    @Slot(object)
    def _cancelled(self, details: dict[str, str]) -> None:
        self.elapsed_timer.stop()
        self.completion_summary.setText(
            f"Operation cancelled safely after stage: {details.get('stage', 'unknown')}\n"
            f"Temporary output removed: {details.get('temporary_file_removed', True)}\n"
            f"Original IFC unchanged: {details.get('source_remains_unchanged', True)}"
        )
        self._apply_state(WorkflowState.FAILED)

    @Slot()
    def cancel(self) -> None:
        self.token.cancel()
        self.cancel_button.setEnabled(False)
        self.progress_detail.setText(
            "Cancellation requested. The current non-interruptible native stage must finish safely."
        )

    @Slot()
    def _update_elapsed(self) -> None:
        if not self.started_at:
            return
        seconds = int((datetime.now() - self.started_at).total_seconds())
        self.elapsed_label.setText(f"Elapsed {seconds // 60:02d}:{seconds % 60:02d}")
        if self.temporary_path and self.temporary_path.exists():
            size = self.temporary_path.stat().st_size
            current = self.progress_detail.text().split("  |  Temporary output:")[0]
            self.progress_detail.setText(
                f"{current}  |  Temporary output: {_format_bytes(size)}"
            )

    @Slot(bool)
    def _toggle_details(self, checked: bool) -> None:
        self.details_text.setVisible(checked)
        self.details_button.setText(
            "Hide Technical Details" if checked else "Technical Details"
        )

    def open_report(self, report_type: str) -> None:
        value = self.report.report_paths.get(report_type) if self.report else None
        path = Path(value) if value else None
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, "Report", "The report is not available.")

    @Slot()
    def open_repaired_ifc(self) -> None:
        path = Path(self.report.output) if self.report and self.report.output else None
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, "Repaired IFC", "The repaired IFC is not available.")

    @Slot()
    def reset(self) -> None:
        self.source_path = None
        self.metadata = None
        self.report = None
        self.report_path = None
        self.file_name.setText("No IFC file selected")
        self.file_meta.setText("Select an IFC file to begin")
        self.file_path.setText("")
        self.output_edit.clear()
        self._clear_metrics()
        self._apply_state(WorkflowState.NO_FILE)

    def dragEnterEvent(self, event: Any) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().casefold().endswith(".ifc"):
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        self._set_source(Path(event.mimeData().urls()[0].toLocalFile()))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread and self.thread.isRunning():
            answer = QMessageBox.question(
                self, "Operation in progress",
                "An IFC operation is still running. Request safe cancellation and keep the app open?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.cancel()
            event.ignore()
            return
        event.accept()
