from __future__ import annotations

import re
import traceback
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
    QMenu, QRadioButton, QScrollArea, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import __version__
from ..config import RepairConfig
from ..errors import CancelledError
from ..file_io import SUPPORTED_INPUT_SUFFIXES, prepare_input
from ..models import RepresentationClassification, RunReport, Status
from ..naming import default_repaired_path, overwrite_backup_path
from ..output_safety import cleanup_abandoned_temps
from ..prepared_analysis import PreparedRepairAnalysis
from ..repair import analyse, prepare_repair_analysis, repair_file
from ..telemetry import StageUpdate
from ..utils import format_bytes
from ..workers import CancellationToken


LIGHT_STYLE = """
* { font-family:"Segoe UI"; }
QMainWindow, QWidget#root, QScrollArea#scroll { background:#f4f5f7; color:#182230; }
QFrame#card { background:#ffffff; border:1px solid #e4e7ec; border-radius:14px; }
QFrame#metricCard { background:#ffffff; border:1px solid #e4e7ec; border-radius:12px; }
QFrame#successCard { background:#f4fbf6; border:1px solid #b7dfc1; border-radius:14px; }
QFrame#errorCard { background:#fff6f5; border:1px solid #f2b8b5; border-radius:14px; }
QLabel#muted { color:#667085; }
QLabel#eyebrow { color:#175cd3; font-size:11px; font-weight:700; }
QLabel#title { font-size:28px; font-weight:700; color:#101828; }
QLabel#subtitle { color:#475467; font-size:13px; }
QLabel#section { font-size:14px; font-weight:700; color:#101828; }
QLabel#status { padding:7px 13px; border-radius:14px; background:#eaf2ff; color:#175cd3; font-weight:600; }
QLabel#stageActive { color:#175cd3; font-weight:700; padding:6px; }
QLabel#stageDone { color:#067647; font-weight:700; padding:6px; }
QLabel#stagePending { color:#98a2b3; padding:6px; }
QLabel#metricValue { font-size:25px; font-weight:700; color:#101828; }
QLabel#metricLabel { color:#667085; font-size:11px; }
QLabel#assessmentValue { color:#101828; font-size:15px; font-weight:700; }
QPushButton { min-height:22px; border:1px solid #d0d5dd; border-radius:8px; background:#fff; color:#344054; padding:9px 16px; }
QPushButton:hover { background:#f9fafb; border-color:#98a2b3; }
QPushButton:focus { border:2px solid #84adff; padding:8px 15px; }
QPushButton:disabled { color:#98a2b3; background:#f2f4f7; border-color:#eaecf0; }
QPushButton#primary { color:#fff; background:#175cd3; border-color:#175cd3; font-weight:700; }
QPushButton#primary:hover { background:#1849a9; }
QPushButton#quiet { background:transparent; border-color:transparent; color:#475467; }
QRadioButton { spacing:9px; padding:7px 10px; font-weight:600; }
QLineEdit { border:1px solid #d0d5dd; border-radius:8px; background:#fff; padding:9px; }
QProgressBar { border:0; border-radius:8px; background:#eaecf0; min-height:16px; max-height:16px; text-align:center; color:#182230; font-weight:600; }
QProgressBar::chunk { border-radius:8px; background:#175cd3; }
QFrame#progressCard { background:#f5f9ff; border:2px solid #84adff; border-radius:14px; }
QScrollBar:vertical { background:#eef1f5; width:14px; margin:2px; border-radius:7px; }
QScrollBar::handle:vertical { background:#98a2b3; min-height:48px; border-radius:5px; margin:1px; }
QScrollBar::handle:vertical:hover { background:#667085; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
"""

class WorkflowState(Enum):
    NO_FILE = "Select IFC"
    READY_TO_SCAN = "Ready"
    SCANNING = "Checking"
    ISSUES_FOUND = "Results Ready"
    NO_ISSUES = "Review Complete"
    REPAIRING = "Repairing"
    COMPLETED = "Completed"
    FAILED = "Repair Failed"


@dataclass(slots=True)
class FileMetadata:
    path: Path
    size: int
    modified: datetime
    schema: str | None


@dataclass(frozen=True, slots=True)
class PreparedScanResult:
    report: RunReport
    prepared_analysis: PreparedRepairAnalysis


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


class Metric(QFrame):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(3)
        self.value = QLabel("0")
        self.value.setObjectName("metricValue")
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        caption.setWordWrap(True)
        layout.addWidget(self.value)
        layout.addWidget(caption)

    def set_value(self, value: int | str) -> None:
        self.value.setText(f"{value:,}" if isinstance(value, int) else str(value))


def _format_duration(value: float) -> str:
    seconds = max(0, int(round(value)))
    minutes, seconds = divmod(seconds, 60)
    if minutes:
        return f"{minutes} min {seconds} sec"
    return f"{seconds} sec"


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
        self.setWindowTitle(f"IFC+SG Repair Assistant v{__version__}")
        self.resize(1120, 930)
        self.setMinimumSize(920, 700)
        self.setAcceptDrops(True)
        self.settings = QSettings("BCA", "IFCSGRepairAssistant")
        recent_directory = self.settings.value("last_output_directory", "")
        if recent_directory:
            cleanup_abandoned_temps(Path(str(recent_directory)), older_than_hours=24.0)
        self.state = WorkflowState.NO_FILE
        self.source_path: Path | None = None
        self.metadata: FileMetadata | None = None
        self.report: RunReport | None = None
        self.report_path: Path | None = None
        self.prepared_analysis: PreparedRepairAnalysis | None = None
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
        layout.setContentsMargins(34, 28, 34, 34)
        layout.setSpacing(15)
        self.content_layout = layout

        header = QHBoxLayout()
        titles = QVBoxLayout()
        eyebrow = QLabel("IFC+SG  •  AUTODESK REVIT 2025 / 2026  •  CORENET X")
        eyebrow.setObjectName("eyebrow")
        title = QLabel(f"IFC+SG Repair Assistant  v{__version__}")
        title.setObjectName("title")
        subtitle = QLabel(
            "Repairs missing IfcShapeRepresentation context references in supported "
            "Revit 2025/2026 IFC+SG exports. This IFC4 schema non-compliance can "
            "cause elements to be missing during CORENET X model processing."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(eyebrow)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        self.status_badge = QLabel("Ready")
        self.status_badge.setObjectName("status")
        header.addLayout(titles, 1)
        header.addWidget(
            self.status_badge, 0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        layout.addLayout(header)

        stages = self._card()
        stage_layout = QHBoxLayout(stages)
        stage_layout.setContentsMargins(18, 11, 18, 11)
        self.stage_labels = []
        for index, text in enumerate(("1  Select IFC", "2  Review Results", "3  Repair IFC")):
            label = QLabel(text)
            label.setObjectName("stagePending")
            self.stage_labels.append(label)
            stage_layout.addWidget(label)
            if index < 2:
                divider = QLabel("━━━━━━━━━━━━")
                divider.setObjectName("muted")
                stage_layout.addWidget(divider, 1)
        layout.addWidget(stages)

        self.progress_card = self._build_progress_card()
        layout.addWidget(self.progress_card)
        self.file_card = self._build_file_card()
        layout.addWidget(self.file_card)
        self.assessment_card = self._build_assessment_card()
        layout.addWidget(self.assessment_card)
        layout.addWidget(self._build_repair_mode_card())
        self.results_card = self._build_results_card()
        layout.addWidget(self.results_card)
        self.repair_summary_card = self._build_repair_summary_card()
        layout.addWidget(self.repair_summary_card)
        # Legacy engineering widgets remain instantiated for compatibility with
        # existing report data, but are deliberately not exposed in the modeller UI.
        self.classification_card = self._build_classification_card()
        self.classification_card.setVisible(False)
        self.action_message = QLabel("")
        self.action_message.setWordWrap(True)
        self.action_message.setStyleSheet(
            "font-size:13px;font-weight:600;color:#344054;padding:2px 2px;"
        )
        layout.addWidget(self.action_message)
        self.output_card = self._build_output_card()
        self.output_card.setVisible(False)
        self.action_row = self._build_action_row()
        layout.addWidget(self.action_row)
        self.completion_card = self._build_completion_card()
        layout.addWidget(self.completion_card)
        disclaimer = QLabel(
            "This application performs targeted repairs for known IFC+SG export issues. "
            "It is not a complete IFC validator or CORENET X compliance checker. "
            "A repaired IFC should still undergo the normal submission validation process."
        )
        disclaimer.setObjectName("muted")
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet("font-size:11px;padding:4px 3px;")
        layout.addWidget(disclaimer)
        layout.addStretch(1)
        scroll.setWidget(content)
        self.scroll_area = scroll
        outer.addWidget(scroll)
        self.setCentralWidget(root)

    def _build_file_card(self) -> QFrame:
        card = self._card()
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 13, 16, 13)
        heading = QLabel("Selected IFC")
        heading.setObjectName("section")
        self.file_name = QLabel("No IFC file selected")
        self.file_name.setStyleSheet("font-weight:700;")
        self.file_meta = QLabel("Choose an IFC, IFCZIP, or ZIP file to begin")
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
        self.file_path.setVisible(False)
        layout.setColumnStretch(1, 1)
        return card

    def _build_repair_mode_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(7)
        heading = QLabel("Repair Mode")
        heading.setObjectName("section")
        modes = QHBoxLayout()
        self.repair_mode_group = QButtonGroup(self)
        self.repair_mode_audit = QRadioButton("Audit Only")
        self.repair_mode_repair = QRadioButton("Repair IFC")
        self.repair_mode_group.addButton(self.repair_mode_audit)
        self.repair_mode_group.addButton(self.repair_mode_repair)
        self.repair_mode_repair.setChecked(True)
        self.repair_mode_audit.toggled.connect(self._repair_mode_changed)
        self.repair_mode_repair.toggled.connect(self._repair_mode_changed)
        modes.addWidget(self.repair_mode_audit)
        modes.addWidget(self.repair_mode_repair)
        modes.addStretch(1)
        self.repair_mode_note = QLabel(
            "Check the IFC, repair all supported direct-product geometry references "
            "that can be resolved safely, and verify the repaired IFC."
        )
        self.repair_mode_note.setObjectName("muted")
        self.repair_mode_note.setWordWrap(True)
        layout.addWidget(heading)
        layout.addLayout(modes)
        layout.addWidget(self.repair_mode_note)
        return card

    def _build_assessment_card(self) -> QFrame:
        card = self._card()
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        heading = QLabel("File Assessment")
        heading.setObjectName("section")
        self.assessment_schema = QLabel("Schema: —")
        self.assessment_exporter = QLabel("Likely authoring tool: —")
        self.assessment_ifcsg = QLabel("IFC+SG identification: —")
        self.assessment_strategy = QLabel("Processing strategy: —")
        self.assessment_size = QLabel("—")
        self.assessment_size.setObjectName("assessmentValue")
        self.assessment_status = QLabel("")
        self.assessment_status.setWordWrap(True)
        self.assessment_status.setStyleSheet(
            "background:#eff8ff;color:#175cd3;border-radius:8px;padding:10px;"
        )
        self.assessment_evidence = QLabel("")
        self.assessment_evidence.setObjectName("muted")
        self.assessment_evidence.setWordWrap(True)
        layout.addWidget(heading, 0, 0, 1, 2)
        layout.addWidget(self.assessment_schema, 1, 0)
        layout.addWidget(self.assessment_exporter, 1, 1)
        layout.addWidget(self.assessment_ifcsg, 2, 0)
        layout.addWidget(self.assessment_strategy, 2, 1)
        layout.addWidget(self.assessment_evidence, 3, 0, 1, 2)
        layout.addWidget(self.assessment_size, 2, 1)
        layout.addWidget(self.assessment_status, 3, 0, 1, 2)
        self.assessment_strategy.setVisible(False)
        self.assessment_evidence.setVisible(False)
        return card

    def _build_results_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        heading = QLabel("Results Summary")
        heading.setObjectName("section")
        layout.addWidget(heading)
        grid = QGridLayout()
        labels = [
            "Geometry References Found",
            "Ready to Repair",
            "Items Remaining",
            "IFC Verification",
        ]
        self.metrics: dict[str, Metric] = {}
        for index, label in enumerate(labels):
            metric = Metric(label)
            self.metrics[label] = metric
            grid.addWidget(metric, 0, index)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        self.breakdown = QLabel("")
        self.breakdown.setObjectName("muted")
        self.breakdown.setWordWrap(True)
        self.breakdown.setVisible(False)
        layout.addWidget(self.breakdown)
        return card

    def _build_repair_summary_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 16)
        heading = QLabel("Repair Summary")
        heading.setObjectName("section")
        self.repair_summary = QLabel(
            "The results will explain whether the supported Revit export issue was found."
        )
        self.repair_summary.setWordWrap(True)
        self.repair_summary.setStyleSheet("color:#344054;line-height:1.5;")
        layout.addWidget(heading)
        layout.addWidget(self.repair_summary)
        return card

    def _build_classification_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        heading = QLabel("Missing Representation Context Classification")
        heading.setObjectName("section")
        note = QLabel(
            "Expand a category to inspect records. Complete details remain available "
            "in the HTML engineering report."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.classification_tree = QTreeWidget()
        self.classification_tree.setColumnCount(7)
        self.classification_tree.setHeaderLabels([
            "Category / STEP ID", "Signature", "Ultimate Product",
            "Usages", "Candidate", "Confidence", "Proposed Action",
        ])
        self.classification_tree.setAlternatingRowColors(True)
        self.classification_tree.setUniformRowHeights(True)
        self.classification_tree.itemExpanded.connect(
            self._populate_classification_category
        )
        layout.addWidget(heading)
        layout.addWidget(note)
        layout.addWidget(self.classification_tree)
        return card

    def _build_output_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        heading = QLabel("Output")
        heading.setObjectName("section")
        layout.addWidget(heading)
        self.save_as_radio = QRadioButton("Save as a new repaired file (recommended)")
        self.replace_radio = QRadioButton("Replace original file")
        modes = QButtonGroup(self)
        modes.addButton(self.save_as_radio)
        modes.addButton(self.replace_radio)
        self.save_as_radio.setChecked(True)
        self.replace_radio.setVisible(False)
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
        self.full_validation = QCheckBox("Run optional full IFC schema validation")
        self.full_validation.setToolTip(
            "Optional. Full validation can take significantly longer for large models."
        )
        self.full_validation.setChecked(False)
        layout.addWidget(self.full_validation)
        return card

    def _build_action_row(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scan_button = QPushButton("Review IFC")
        self.scan_button.clicked.connect(self.scan)
        self.repair_button = QPushButton("Repair IFC")
        self.repair_button.clicked.connect(self.repair)
        layout.addStretch(1)
        layout.addWidget(self.scan_button)
        layout.addWidget(self.repair_button)
        return widget

    def _build_progress_card(self) -> QFrame:
        card = self._card("progressCard")
        card.setAccessibleName("Current IFC operation progress")
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
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
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
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        self.completion_title = QLabel("Repair Completed")
        self.completion_title.setStyleSheet("font-size:20px;font-weight:700;color:#05603a;")
        self.completion_summary = QLabel("")
        self.completion_summary.setWordWrap(True)
        self.completion_summary.setStyleSheet("font-size:13px;color:#344054;")
        layout.addWidget(self.completion_title)
        layout.addWidget(self.completion_summary)
        buttons = QHBoxLayout()
        self.open_ifc_button = QPushButton("Open Repaired IFC")
        self.open_ifc_button.clicked.connect(self.open_repaired_ifc)
        self.report_button = QPushButton("Open Detailed Report")
        self.report_button.setObjectName("primary")
        self.report_menu = QMenu(self.report_button)
        self.html_report_action = QAction("Open Detailed Report", self)
        self.pdf_report_action = QAction("Open PDF Summary", self)
        self.repaired_ifc_action = QAction("Open Repaired IFC", self)
        self.html_report_action.triggered.connect(
            lambda: self.open_report("html")
        )
        self.pdf_report_action.triggered.connect(
            lambda: self.open_report("pdf")
        )
        self.repaired_ifc_action.triggered.connect(self.open_repaired_ifc)
        self.report_button.clicked.connect(lambda: self.open_report("html"))
        self.another_button = QPushButton("Check Another IFC")
        self.another_button.clicked.connect(self.reset)
        buttons.addWidget(self.open_ifc_button)
        buttons.addWidget(self.report_button)
        buttons.addWidget(self.another_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
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
        if state in {WorkflowState.COMPLETED, WorkflowState.NO_ISSUES}:
            badge_background, badge_colour = "#ecfdf3", "#067647"
        elif state == WorkflowState.FAILED:
            badge_background, badge_colour = "#fef3f2", "#b42318"
        else:
            badge_background, badge_colour = "#eaf2ff", "#175cd3"
        self.status_badge.setStyleSheet(
            f"padding:7px 13px;border-radius:14px;background:{badge_background};"
            f"color:{badge_colour};font-weight:600;"
        )
        busy = state in {WorkflowState.SCANNING, WorkflowState.REPAIRING}
        self.select_button.setEnabled(not busy)
        self.assessment_card.setVisible(
            self.report is not None or state in {
                WorkflowState.SCANNING, WorkflowState.REPAIRING
            }
        )
        self.results_card.setVisible(state not in {WorkflowState.NO_FILE, WorkflowState.READY_TO_SCAN})
        self.repair_summary_card.setVisible(
            state not in {
                WorkflowState.NO_FILE, WorkflowState.READY_TO_SCAN,
                WorkflowState.COMPLETED, WorkflowState.FAILED,
            }
        )
        self.classification_card.setVisible(False)
        self.output_card.setVisible(False)
        self.progress_card.setVisible(busy)
        self.completion_card.setVisible(state in {WorkflowState.COMPLETED, WorkflowState.FAILED})
        self.scan_button.setVisible(state not in {WorkflowState.NO_FILE, WorkflowState.COMPLETED})
        self.repair_button.setVisible(state in {WorkflowState.ISSUES_FOUND, WorkflowState.REPAIRING})
        self.action_row.setVisible(
            state not in {WorkflowState.NO_FILE, WorkflowState.COMPLETED}
        )
        self.cancel_button.setVisible(busy)

        if state == WorkflowState.NO_FILE:
            self._set_primary(self.select_button)
            self.select_button.setText("Select IFC")
            self.scan_button.setEnabled(False)
            self.repair_button.setEnabled(False)
            self.action_message.setText(
                "Select an IFC+SG file exported from Autodesk Revit 2025 or Revit 2026."
            )
            stage = 0
        elif state == WorkflowState.READY_TO_SCAN:
            self._set_primary(self.scan_button)
            self.select_button.setText("Change IFC")
            self.scan_button.setText("Review IFC")
            self.scan_button.setEnabled(True)
            self.repair_button.setEnabled(False)
            self.action_message.setText(
                "Select Review IFC to check for the supported Revit IFC export issue."
            )
            stage = 1
        elif state == WorkflowState.SCANNING:
            self._set_primary(None)
            self.scan_button.setText("Checking...")
            self.scan_button.setEnabled(False)
            self.repair_button.setEnabled(False)
            self.action_message.setText(
                "Reviewing the IFC. You can continue working while this runs."
            )
            stage = 1
        elif state == WorkflowState.ISSUES_FOUND:
            self.select_button.setText("Change IFC")
            repairable = self.report.summary_counts.get("AutomaticallyRepairable", 0) if self.report else 0
            self._set_primary(self.repair_button)
            self.scan_button.setText("Check Again")
            self.scan_button.setEnabled(True)
            mode = self._repair_mode_key()
            label = (
                "Audit Complete"
                if mode == "audit"
                else f"Repair IFC ({repairable:,})"
            )
            self.repair_button.setText(label)
            repair_supported = self._automatic_repair_supported()
            self.repair_button.setEnabled(
                repairable > 0 and mode != "audit" and repair_supported
            )
            self.action_message.setText(
                (
                    f"{repairable:,} supported geometry references are ready "
                    "for repair."
                    if repair_supported else
                    "Automatic repair is unavailable for this file. Audit "
                    "results remain available."
                )
            )
            stage = 2
        elif state == WorkflowState.NO_ISSUES:
            self._set_primary(self.select_button)
            self.select_button.setText("Check Another IFC")
            self.scan_button.setText("Check Again")
            self.scan_button.setEnabled(True)
            self.repair_button.setEnabled(False)
            self.action_message.setText(
                "The known Revit IFC geometry-reference issue was not detected."
            )
            stage = 2
        elif state == WorkflowState.REPAIRING:
            self.select_button.setText("Change IFC")
            self._set_primary(None)
            self.scan_button.setEnabled(False)
            self.repair_button.setText("Repairing IFC...")
            self.repair_button.setEnabled(False)
            self.action_message.setText(
                "Creating and verifying a repaired IFC. The original file will remain unchanged."
            )
            stage = 2
        elif state == WorkflowState.COMPLETED:
            self._set_primary(None)
            self.action_message.setText("")
            self.completion_card.setObjectName("successCard")
            self.completion_title.setText(
                "Audit Completed"
                if self._repair_mode_key() == "audit"
                else (
                    "Repair Completed"
                )
            )
            stage = 3
            QTimer.singleShot(
                0,
                lambda: self.scroll_area.verticalScrollBar().setValue(
                    self.scroll_area.verticalScrollBar().maximum()
                ),
            )
        else:
            self._set_primary(self.scan_button)
            self.scan_button.setText("Check Again")
            self.scan_button.setEnabled(self.source_path is not None)
            self.repair_button.setVisible(False)
            self.repair_button.setEnabled(False)
            self.action_message.setText(
                "The check did not complete. Select Check Again to retry, or choose another IFC."
            )
            self.completion_card.setObjectName("errorCard")
            self.completion_title.setText("Repair Failed")
            stage = 2
            QTimer.singleShot(
                0,
                lambda: self.scroll_area.verticalScrollBar().setValue(
                    self.scroll_area.verticalScrollBar().maximum()
                ),
            )

        for index, label in enumerate(self.stage_labels):
            label.setObjectName(
                "stageDone" if index < stage else
                "stageActive" if index == min(stage, 2) else "stagePending"
            )
            label.style().unpolish(label)
            label.style().polish(label)
        # Apply button availability last so visibility/layout updates cannot
        # leave a previously disabled primary action stale.
        if state == WorkflowState.READY_TO_SCAN:
            self.scan_button.setObjectName("primary")
            self.scan_button.style().unpolish(self.scan_button)
            self.scan_button.style().polish(self.scan_button)
            self.scan_button.setEnabled(True)
        elif state == WorkflowState.ISSUES_FOUND:
            self.scan_button.setEnabled(True)

    @Slot()
    def _choose_source(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self, "Select IFC+SG File", "",
            "IFC and IFC archives (*.ifc *.ifczip *.zip)"
        )
        if value:
            self._set_source(Path(value))

    def _set_source(self, path: Path) -> None:
        if not path.is_file() or path.suffix.casefold() not in SUPPORTED_INPUT_SUFFIXES:
            QMessageBox.warning(
                self, "Invalid input",
                "Select a readable .ifc, .ifczip, or .zip file containing one IFC."
            )
            return
        stat = path.stat()
        self.source_path = path.resolve()
        self.metadata = FileMetadata(
            self.source_path, stat.st_size,
            datetime.fromtimestamp(stat.st_mtime), _read_schema(path),
        )
        self.report = None
        self.report_path = None
        self.prepared_analysis = None
        self.file_name.setText(path.name)
        schema = self.metadata.schema or "Schema will be assessed during pre-scan"
        self.file_meta.setText(
            f"{format_bytes(stat.st_size)}  |  {schema}  |  Modified "
            f"{self.metadata.modified:%d %b %Y, %I:%M %p}"
        )
        self.file_path.setText(str(self.source_path))
        default_output = (
            default_repaired_path(self.source_path)
            if self.source_path.suffix.casefold() == ".ifc"
            else self.source_path.with_name(f"{self.source_path.stem}_repaired.ifc")
        )
        self.output_edit.setText(str(default_output))
        self._clear_metrics()
        self._apply_state(WorkflowState.READY_TO_SCAN)

    def _clear_metrics(self) -> None:
        for metric in self.metrics.values():
            metric.set_value(0)
        self.breakdown.setText("")
        if hasattr(self, "repair_summary"):
            self.repair_summary.setText(
                "The results will explain whether the supported Revit export issue was found."
            )
        if hasattr(self, "classification_tree"):
            self.classification_tree.clear()

    def _repair_mode_key(self) -> str:
        if self.repair_mode_audit.isChecked():
            return "audit"
        return "production"

    @Slot(bool)
    def _repair_mode_changed(self, checked: bool) -> None:
        if not checked:
            return
        mode = self._repair_mode_key()
        notes = {
            "production": (
                "Check the IFC, repair supported direct-product geometry references "
                "that can be resolved safely, and verify the repaired IFC."
            ),
            "audit": (
                "Check the IFC and generate a report without changing the file."
            ),
        }
        self.repair_mode_note.setText(notes[mode])
        if self.source_path and self.state not in {
            WorkflowState.SCANNING, WorkflowState.REPAIRING,
        }:
            self.report = None
            self.prepared_analysis = None
            self._clear_metrics()
            self._apply_state(WorkflowState.READY_TO_SCAN)

    def _automatic_repair_supported(self) -> bool:
        if not self.report or not self.report.file_assessment:
            return False
        assessment = self.report.file_assessment
        if (assessment.schema or "").upper() != "IFC4" or not assessment.ifc_sg:
            return False
        return assessment.ifc_sg.likely_exporter in {
            "Autodesk Revit 2025", "Autodesk Revit 2026",
        }

    @Slot(object)
    def _populate_classification_category(self, category_item: QTreeWidgetItem) -> None:
        category = category_item.data(0, Qt.ItemDataRole.UserRole)
        populated_role = int(Qt.ItemDataRole.UserRole) + 1
        if not category or category_item.data(0, populated_role) or not self.report:
            return
        category_item.takeChildren()
        records = [
            item for item in self.report.diagnoses
            if item.classification.value == category
        ]
        for diagnosis in records:
            proposed = (
                f"#{diagnosis.proposed_context.step_id}"
                if diagnosis.proposed_context else "-"
            )
            product = diagnosis.product_class or "No ultimate product"
            if diagnosis.ultimate_product_count > 1:
                product = f"{diagnosis.ultimate_product_count:,} products"
            child = QTreeWidgetItem([
                f"#{diagnosis.representation_step_id}",
                (
                    f"{diagnosis.representation_identifier or '-'} / "
                    f"{diagnosis.representation_type or '-'}"
                ),
                product,
                f"{diagnosis.usage_count:,}",
                proposed,
                diagnosis.confidence_level.value,
                diagnosis.proposed_action,
            ])
            detail = "\n".join([
                f"Rule: {diagnosis.rule_id or '-'}",
                f"Schema: {diagnosis.schema_status}",
                f"Rendering risk: {diagnosis.rendering_risk}",
                f"Downstream risk: {diagnosis.downstream_processing_risk}",
                f"Priority: {diagnosis.repair_priority}",
                "Evidence: " + "; ".join(diagnosis.evidence + diagnosis.conflicts),
            ])
            for column in range(7):
                child.setToolTip(column, detail)
            category_item.addChild(child)
        category_item.setData(0, populated_role, True)

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
        function: Callable[[Callable[[StageUpdate], None]], object],
    ) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.operation = operation
        self.token = CancellationToken()
        self.started_at = datetime.now()
        self.temporary_path = None
        self.elapsed_timer.start()
        self.progress_stage.setText(
            "Starting IFC review" if operation == "scan" else "Starting IFC repair"
        )
        self.progress.setRange(0, 0)
        self.progress.setFormat("Starting...")
        self.progress_detail.setText(
            "The operation is running. Progress updates will appear here."
        )
        self._apply_state(
            WorkflowState.SCANNING if operation == "scan" else WorkflowState.REPAIRING
        )
        QTimer.singleShot(0, self._show_active_progress)
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
    def _show_active_progress(self) -> None:
        """Keep the running operation visible instead of hiding it below the fold."""
        self.scroll_area.ensureWidgetVisible(self.progress_card, 0, 12)

    @Slot()
    def scan(self) -> None:
        if not self.source_path:
            return
        path = self.source_path

        def operation(telemetry: Callable[[StageUpdate], None]) -> object:
            with prepare_input(path) as prepared:
                if self._repair_mode_key() == "audit":
                    report = analyse(
                        prepared.ifc_path, validate=False, quick=True,
                        cancelled=self.token.cancelled, telemetry=telemetry,
                        repair_mode="audit",
                    )
                    artifact = None
                else:
                    artifact = prepare_repair_analysis(
                        prepared.ifc_path, validate=False, quick=True,
                        cancelled=self.token.cancelled, telemetry=telemetry,
                        repair_mode="production",
                    )
                    report = artifact.report_copy()
                report.source = str(path)
                report.repair_mode = (
                    "Audit Only"
                    if self._repair_mode_key() == "audit"
                    else "Repair IFC"
                )
                if report.file_assessment:
                    report.file_assessment.original_name = path.name
                    report.file_assessment.input_kind = prepared.input_kind
                if artifact is not None:
                    return PreparedScanResult(report, artifact)
                return report

        self._start_job("scan", operation)

    @Slot()
    def repair(self) -> None:
        if not self.source_path or not self.report:
            return
        output = Path(self.output_edit.text()).expanduser().resolve()
        if output == self.source_path:
            QMessageBox.warning(
                self, "Choose a new output", "Save As output must differ from the original."
            )
            return
        if output.exists():
            QMessageBox.warning(
                self, "Output already exists",
                "Choose a different output filename. Existing files are not overwritten in recommended mode.",
            )
            return
        if self.report.file_assessment and self.report.file_assessment.ifc_sg:
            assessment = self.report.file_assessment.ifc_sg
            if assessment.classification.value == "Not identifiable as IFC+SG":
                response = QMessageBox.warning(
                    self,
                    "IFC+SG identification not confirmed",
                    "This file could not be confidently identified as an IFC+SG "
                    "export. Repair rules may not be applicable. Audit Only is "
                    "recommended.\n\nContinue with the selected repair mode?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if response != QMessageBox.StandardButton.Yes:
                    return

        self.settings.setValue("last_output_directory", str(output.parent))
        def operation(telemetry: Callable[[StageUpdate], None]) -> RunReport:
            with prepare_input(self.source_path) as prepared:
                config = RepairConfig(
                    source=prepared.ifc_path,
                    output=output,
                    create_backup=False,
                    replace_original_with_backup=False,
                    full_validation=False,
                    repair_mode=self._repair_mode_key(),
                )
                report = repair_file(
                    config, cancelled=self.token.cancelled, telemetry=telemetry,
                    prepared_analysis=self.prepared_analysis,
                )
                report.source = str(self.source_path)
                report.repair_mode = "Repair IFC"
                if report.file_assessment:
                    report.file_assessment.original_name = self.source_path.name
                    report.file_assessment.input_kind = prepared.input_kind
                return report
        self._start_job("repair", operation)

    @Slot(object)
    def _stage_changed(self, update: StageUpdate) -> None:
        self.current_stage = update
        stage_messages = {
            "input_metadata": "Preparing the selected IFC",
            "step_prescan": "Checking IFC+SG file compatibility",
            "ifc_opening": "Opening the IFC model",
            "collect_target_elements": "Checking geometry references",
            "collect_shape_representations": "Checking geometry references",
            "context_index": "Reviewing available geometry references",
            "opening_relationships": "Reviewing model relationships",
            "context_resolution": "Preparing safe repair recommendations",
            "cache_analysis_fingerprint": "Securing reviewed IFC for repair",
            "cached_analysis_validation": "Confirming the reviewed IFC is unchanged",
            "indirect_context_index": "Reviewing available geometry references",
            "indirect_product_ownership": "Reviewing model relationships",
            "indirect_shape_aspects": "Reviewing indirect geometry references",
            "indirect_representation_index": "Reviewing reusable geometry references",
            "indirect_classification": "Preparing repair results",
            "abandoned_temp_cleanup": "Preparing repaired IFC",
            "output_preflight": "Checking available disk space",
            "build_patch_plan_inputs": "Preparing safe repairs",
            "build_patch_plan": "Preparing safe repairs",
            "validate_patch_plan": "Checking repair plan",
            "create_temporary_output": "Preparing repaired IFC",
            "apply_patches": "Saving repaired IFC",
            "flush_output": "Saving repaired IFC",
            "output_size_verification": "Checking repaired IFC",
            "step_envelope_verification": "Checking repaired IFC structure",
            "targeted_verification": "Verifying repaired geometry references",
            "unexpected_change_audit": "Checking for unexpected model changes",
            "atomic_replacement": "Finalising repaired IFC",
            "generate_pdf_report": "Generating report summary",
            "generate_html_report": "Generating detailed report",
            "repair_complete": "Repair completed",
            "scan_complete": "Review completed",
        }
        message = stage_messages.get(update.stage_id)
        if message is None and update.stage_id.startswith("audit_"):
            message = "Running additional IFC+SG checks"
        self.progress_stage.setText(message or "Checking IFC")
        self.cancel_button.setEnabled(update.cancellable)
        self.cancel_button.setText("Cancel" if update.cancellable else "Stop After Current Stage")
        if update.bytes_processed is not None and update.bytes_total:
            self.progress.setRange(0, 1000)
            self.progress.setFormat("%p%")
            self.progress.setValue(min(1000, int(update.bytes_processed * 1000 / update.bytes_total)))
            detail = (
                f"{format_bytes(update.bytes_processed)} of {format_bytes(update.bytes_total)}  |  "
                f"{update.bytes_processed * 100 / update.bytes_total:.0f}%"
            )
            if update.throughput_bytes_per_second is not None:
                detail += f"  |  {format_bytes(int(update.throughput_bytes_per_second))}/s"
            if update.elapsed_seconds is not None:
                detail += f"  |  Elapsed {int(update.elapsed_seconds)//60:02d}:{int(update.elapsed_seconds)%60:02d}"
            if update.estimated_remaining_seconds is not None:
                remaining = max(0, int(update.estimated_remaining_seconds))
                detail += f"  |  Remaining {remaining//60:02d}:{remaining%60:02d}"
            if update.current is not None and update.total:
                detail += f"  |  Repairs {update.current:,}/{update.total:,}"
        elif update.current is not None and update.total:
            self.progress.setRange(0, update.total)
            self.progress.setFormat("%p%")
            self.progress.setValue(update.current)
            detail = f"{update.current:,} of {update.total:,}"
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat("Working...")
            detail = "This stage may take several minutes for large IFC files."
        if update.temporary_path:
            self.temporary_path = update.temporary_path
        if update.output_size is not None:
            detail += f"  |  Saved: {format_bytes(update.output_size)}"
        self.progress_detail.setText(detail)

    @Slot(object)
    def _completed(self, result: object) -> None:
        self.elapsed_timer.stop()
        if isinstance(result, PreparedScanResult):
            report = result.report
            self.prepared_analysis = result.prepared_analysis
        elif isinstance(result, RunReport):
            report = result
            if self.operation == "scan":
                self.prepared_analysis = None
        else:
            raise TypeError(f"Unexpected worker result: {type(result).__name__}")
        self.report = report
        self.temporary_path = None
        if self.operation == "scan":
            self._show_scan_results(report)
            if self._repair_mode_key() == "audit":
                self.html_report_action.setEnabled(
                    bool(report.report_paths.get("html"))
                )
                self.pdf_report_action.setEnabled(
                    bool(report.report_paths.get("pdf"))
                )
                self.repaired_ifc_action.setEnabled(False)
                self.open_ifc_button.setEnabled(False)
                self.report_button.setEnabled(True)
                self.completion_title.setText("Audit Completed")
                review = (
                    report.summary_counts.get("ReportOnlyFindings", 0)
                    + report.summary_counts.get("AmbiguousFindings", 0)
                )
                self.completion_summary.setText(
                    f"{report.summary_counts.get('AffectedRepresentations', 0):,} "
                    f"supported geometry references detected\n"
                    f"{review:,} supported item(s) remain\n\n"
                    "✓  Original IFC preserved\n"
                    "✓  Detailed report created\n\n"
                    f"Completed in {_format_duration(report.total_duration_seconds)}"
                )
                self._apply_state(WorkflowState.COMPLETED)
                return
            if report.diagnoses or report.audit_findings:
                self._apply_state(WorkflowState.ISSUES_FOUND)
            else:
                self._apply_state(WorkflowState.NO_ISSUES)
            return

        self._show_scan_results(report)
        html = report.report_paths.get("html")
        self.report_path = Path(html) if html else None
        repaired = report.summary_counts.get("SuccessfullyRepaired", 0)
        remaining = report.summary_counts.get("TargetedIssuesRemaining", 0)
        verification = bool(report.targeted_verification.get("passed"))
        duration = report.total_duration_seconds or sum(report.durations.values())
        output_name = Path(report.output).name if report.output else "Not created"
        self.completion_summary.setText(
            f"{repaired:,} geometry references repaired\n"
            f"{remaining:,} supported issues remaining\n\n"
            f"{'✓' if verification else '•'}  IFC "
            f"{'verified' if verification else 'verification requires review'}\n"
            f"{'✓' if report.change_audit.get('passed') else '•'}  "
            f"{'No unexpected model changes detected' if report.change_audit.get('passed') else 'Change verification requires review'}\n"
            "✓  Original IFC preserved\n\n"
            f"Output\n{output_name}\n\n"
            f"Completed in {_format_duration(duration)}"
        )
        self.html_report_action.setEnabled(bool(report.report_paths.get("html")))
        self.pdf_report_action.setEnabled(bool(report.report_paths.get("pdf")))
        self.repaired_ifc_action.setEnabled(bool(report.output))
        self.open_ifc_button.setEnabled(bool(report.output))
        self.report_button.setEnabled(any((
            self.html_report_action.isEnabled(), self.pdf_report_action.isEnabled(),
            self.repaired_ifc_action.isEnabled(),
        )))
        self.details_text.setText(self._technical_details(report))
        self._apply_state(WorkflowState.COMPLETED)

    def _show_classification_results(self, report: RunReport) -> None:
        self.classification_tree.clear()
        labels = {
            RepresentationClassification.DIRECT_PRODUCT.value: "Direct Product",
            RepresentationClassification.SHAPE_ASPECT_PRODUCT.value:
                "Shape Aspect - Product",
            RepresentationClassification.REPRESENTATION_MAP.value:
                "Reusable Representation Map",
            RepresentationClassification.SHAPE_ASPECT_REPRESENTATION_MAP.value:
                "Shape Aspect - Representation Map",
            RepresentationClassification.ORPHANED.value: "Orphaned",
            RepresentationClassification.AMBIGUOUS.value: "Ambiguous",
            RepresentationClassification.UNSUPPORTED.value: "Unsupported",
        }
        for category in RepresentationClassification:
            values = report.classification_counts.get(category.value, {})
            detected = values.get("detected", 0)
            if not detected:
                continue
            parent = QTreeWidgetItem([
                f"{labels[category.value]} ({detected:,})",
                "",
                "",
                "",
                "",
                f"HIGH: {values.get('high_confidence', 0):,}",
                (
                    f"Auto-repair {values.get('auto_repair', 0):,}; "
                    f"report only {values.get('reported_only', 0):,}"
                ),
            ])
            parent.setData(0, Qt.ItemDataRole.UserRole, category.value)
            parent.addChild(QTreeWidgetItem(["Loading..."]))
            self.classification_tree.addTopLevelItem(parent)
        for category_name in (
            "Space Geometry",
            "Quantity Information",
            "Georeferencing",
            "IFC Structure",
            "Other IFC+SG Checks",
        ):
            findings = [
                item for item in report.audit_findings
                if item.category == category_name
            ]
            if not findings:
                continue
            parent = QTreeWidgetItem([
                f"{category_name} ({len(findings):,})",
                "",
                "",
                "",
                "",
                "REPORT ONLY",
                "No change applied",
            ])
            for finding in findings[:500]:
                parent.addChild(QTreeWidgetItem([
                    f"{finding.rule_id} / #{finding.entity_step_id or '—'}",
                    finding.title,
                    finding.entity_type or "—",
                    finding.submission_risk,
                    "",
                    finding.confidence,
                    finding.action,
                ]))
            self.classification_tree.addTopLevelItem(parent)
        for column in range(7):
            self.classification_tree.resizeColumnToContents(column)

    def _show_scan_results(self, report: RunReport) -> None:
        counts = report.summary_counts
        values = {
            "Geometry References Found": counts.get("AffectedRepresentations", 0),
            "Ready to Repair": counts.get("SupportedRepairs", 0),
            "Items Remaining": counts.get("NotAutomaticallyRepairable", 0),
            "IFC Verification": (
                "Verified" if report.targeted_verification.get("passed") else "Ready"
            ),
        }
        for key, value in values.items():
            self.metrics[key].set_value(value)
        self.breakdown.setText("")
        self.details_text.setText(self._technical_details(report))
        issue_count = counts.get("AffectedRepresentations", 0)
        ready = counts.get("SupportedRepairs", 0)
        self.repair_summary.setText(
            "\n".join((
                (
                    "✓  Known Revit IFC export issue detected"
                    if issue_count else
                    "✓  Known Revit IFC export issue was not detected"
                ),
                (
                    "✓  Supported direct-product repair is available"
                    if ready and self._automatic_repair_supported() else
                    "•  No production-approved repair is available for this file"
                ),
                f"•  {counts.get('NotAutomaticallyRepairable', 0):,} supported "
                "item(s) could not be resolved automatically",
                "✓  Original IFC will remain unchanged",
                (
                    "✓  A repaired IFC will be created"
                    if ready and self._repair_mode_key() == "production"
                    and self._automatic_repair_supported() else
                    "✓  Audit report will be created without changing the IFC"
                ),
            ))
        )
        assessment = report.file_assessment
        if assessment:
            self.assessment_schema.setText(
                f"IFC Schema\n{assessment.schema or 'Unknown'}"
            )
            ifc_sg = assessment.ifc_sg
            self.assessment_exporter.setText(
                f"Authoring Tool\n"
                f"{ifc_sg.likely_exporter if ifc_sg else 'Unknown'}"
            )
            self.assessment_ifcsg.setText(
                "Workflow\n"
                + (
                    "IFC+SG Detected"
                    if ifc_sg and ifc_sg.classification.value == "Likely IFC+SG"
                    else ifc_sg.classification.value if ifc_sg else "Not assessed"
                )
            )
            self.assessment_size.setText(f"File Size\n{format_bytes(assessment.size_bytes)}")
            if self._automatic_repair_supported():
                status = "This file is suitable for the supported IFC+SG repair workflow."
                colour, background = "#175cd3", "#eff8ff"
            else:
                status = (
                    "This file is outside the currently supported repair workflow. "
                    "Audit results are still available. Automatic repair has been disabled."
                )
                colour, background = "#b54708", "#fffaeb"
            self.assessment_status.setText(status)
            self.assessment_status.setStyleSheet(
                f"background:{background};color:{colour};border-radius:8px;padding:10px;"
            )
            evidence = (ifc_sg.evidence + ifc_sg.warnings) if ifc_sg else []
            self.assessment_evidence.setText(" • ".join(evidence))

    @staticmethod
    def _technical_details(report: RunReport) -> str:
        timings = "\n".join(
            f"{key.replace('_', ' ').title()}: {value:.3f} seconds"
            for key, value in report.durations.items()
        )
        return (
            f"Rule: {report.active_rule_id} v{report.active_rule_version}\n"
            f"Schema: {report.schema}\nInput: {report.source}\n"
            f"Selected rules: {', '.join(report.selected_rules) or 'None'}\n"
            f"Skipped rules: {len(report.skipped_rules)}\n"
            f"Output: {report.output or 'Not written'}\n"
            f"Diagnostic log: {report.log_path or 'Not created'}\n\n{timings}"
        )

    @Slot(object)
    def _failed(self, details: dict[str, str]) -> None:
        self.elapsed_timer.stop()
        quarantined = details.get("quarantined_output_path")
        retained_message = (
            "A failed test output was quarantined for diagnostics."
            if quarantined
            else "Incomplete output removed."
        )
        self.completion_summary.setText(
            "The repair could not be completed safely.\n\n"
            "✓  Original IFC preserved\n"
            f"✓  {retained_message}\n\n"
            "No repaired IFC was published. Open Technical Details for diagnostic information."
        )
        self.details_text.setText(
            f"Stage: {details.get('stage', 'unknown')}\n"
            f"{details.get('type', 'Error')}: {details.get('message', 'Unknown error')}\n"
            f"Temporary output removed: {details.get('temporary_file_removed', True)}\n"
            f"Quarantined diagnostic IFC: {quarantined or 'Not retained'}\n"
            f"Failure report: {details.get('failure_report_path') or 'Not created'}\n"
            f"Output: {details.get('final_output_path', self.output_edit.text())}\n"
            f"Debug log: {details.get('log_path') or 'Not enabled'}"
        )
        self.open_ifc_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self._apply_state(WorkflowState.FAILED)

    @Slot(object)
    def _cancelled(self, details: dict[str, str]) -> None:
        self.elapsed_timer.stop()
        self.completion_summary.setText(
            "The operation was cancelled safely.\n\n"
            "✓  Original IFC preserved\n"
            "✓  Incomplete output removed"
        )
        self.details_text.setText(
            f"Cancelled after stage: {details.get('stage', 'unknown')}\n"
            f"Temporary output removed: {details.get('temporary_file_removed', True)}"
        )
        self.open_ifc_button.setEnabled(False)
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
            current = self.progress_detail.text().split("  |  Saved:")[0]
            self.progress_detail.setText(
                f"{current}  |  Saved: {format_bytes(size)}"
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
        self.prepared_analysis = None
        self.file_name.setText("No IFC file selected")
        self.file_meta.setText("Choose an IFC, IFCZIP, or ZIP file to begin")
        self.file_path.setText("")
        self.output_edit.clear()
        self._clear_metrics()
        self._apply_state(WorkflowState.NO_FILE)

    def dragEnterEvent(self, event: Any) -> None:
        urls = event.mimeData().urls()
        if urls and Path(urls[0].toLocalFile()).suffix.casefold() in SUPPORTED_INPUT_SUFFIXES:
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
            else:
                event.accept()
            return
        event.accept()
