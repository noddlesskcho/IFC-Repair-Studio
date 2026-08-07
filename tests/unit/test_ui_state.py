import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from ifc_context_repair import __version__
from ifc_context_repair.models import RunReport
from ifc_context_repair.ui.main_window import MainWindow, WorkflowState


class UiStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()

    def test_repair_disabled_before_scan_and_scan_is_primary(self):
        self.window._apply_state(WorkflowState.READY_TO_SCAN)
        self.assertIsNot(WorkflowState.NO_FILE, WorkflowState.READY_TO_SCAN)
        self.assertTrue(self.window.scan_button.isEnabled())
        self.assertFalse(self.window.scan_button.isHidden())
        self.assertFalse(self.window.action_row.isHidden())
        self.assertEqual(self.window.scan_button.objectName(), "primary")
        self.assertEqual(self.window.scan_button.text(), "Review IFC")
        self.assertEqual(self.window.select_button.text(), "Change IFC")
        self.assertIn("Select Review IFC", self.window.action_message.text())
        self.assertFalse(self.window.repair_button.isEnabled())

    def test_repair_becomes_primary_after_issues_found(self):
        self.window.report = RunReport(
            source="sample.ifc",
            summary_counts={"AutomaticallyRepairable": 3151, "ElementsAffected": 2051},
        )
        self.window._apply_state(WorkflowState.ISSUES_FOUND)
        self.assertEqual(self.window.repair_button.objectName(), "primary")
        self.assertEqual(self.window.scan_button.objectName(), "")
        self.assertEqual(self.window.scan_button.text(), "Check Again")
        self.assertIn("3,151", self.window.repair_button.text())

    def test_no_repair_action_when_no_issues(self):
        self.window._apply_state(WorkflowState.NO_ISSUES)
        self.assertTrue(self.window.repair_button.isHidden())

    def test_failed_check_can_be_retried(self):
        self.window.source_path = Path("sample.ifc")
        self.window.metadata = Mock()
        self.window._apply_state(WorkflowState.FAILED)
        self.assertFalse(self.window.action_row.isHidden())
        self.assertFalse(self.window.scan_button.isHidden())
        self.assertTrue(self.window.scan_button.isEnabled())
        self.assertEqual(self.window.scan_button.text(), "Check Again")
        self.assertEqual(self.window.scan_button.objectName(), "primary")
        self.assertTrue(self.window.repair_button.isHidden())
        self.window._start_job = Mock()
        self.window.scan_button.click()
        self.window._start_job.assert_called_once()
        self.assertEqual(self.window._start_job.call_args.args[0], "scan")

    def test_simplified_ui_has_no_theme_or_folder_controls(self):
        self.assertFalse(hasattr(self.window, "theme_button"))
        self.assertFalse(hasattr(self.window, "open_source_folder_button"))
        self.assertFalse(hasattr(self.window, "output_folder_button"))

    def test_completion_uses_direct_user_actions(self):
        self.assertEqual(self.window.open_ifc_button.text(), "Open Repaired IFC")
        self.assertEqual(self.window.report_button.text(), "Open Detailed Report")
        self.assertEqual(self.window.another_button.text(), "Check Another IFC")

    def test_two_version1_user_facing_modes(self):
        self.assertEqual(self.window.repair_mode_audit.text(), "Audit Only")
        self.assertEqual(self.window.repair_mode_repair.text(), "Repair IFC")
        self.assertFalse(hasattr(self.window, "repair_mode_compatibility"))
        self.assertTrue(self.window.repair_mode_repair.isChecked())

    def test_title_displays_version_and_ifc_schema_issue(self):
        self.assertIn(f"v{__version__}", self.window.windowTitle())
        visible_text = " ".join(
            label.text() for label in self.window.findChildren(type(self.window.status_badge))
        )
        self.assertIn(f"v{__version__}", visible_text)
        self.assertIn("IfcShapeRepresentation", visible_text)
        self.assertIn("IFC4 schema non-compliance", visible_text)

    def test_engineering_classification_is_not_exposed(self):
        self.assertTrue(self.window.classification_card.isHidden())
        self.assertTrue(self.window.output_card.isHidden())

    def test_active_progress_is_prominent_and_above_file_details(self):
        self.assertLess(
            self.window.content_layout.indexOf(self.window.progress_card),
            self.window.content_layout.indexOf(self.window.file_card),
        )
        self.assertEqual(self.window.progress_card.objectName(), "progressCard")
        self.assertEqual(
            self.window.progress_card.accessibleName(),
            "Current IFC operation progress",
        )
        self.assertIn("QScrollBar:vertical", self.window.styleSheet())
        self.window._apply_state(WorkflowState.SCANNING)
        self.assertFalse(self.window.progress_card.isHidden())

    def test_close_during_operation_keeps_open_only_when_cancellation_requested(self):
        thread = Mock()
        thread.isRunning.return_value = True
        self.window.thread = thread
        self.window.cancel = Mock()

        keep_open_event = Mock()
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window.closeEvent(keep_open_event)
        self.window.cancel.assert_called_once_with()
        keep_open_event.ignore.assert_called_once_with()
        keep_open_event.accept.assert_not_called()

        self.window.cancel.reset_mock()
        close_event = Mock()
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.No,
        ):
            self.window.closeEvent(close_event)
        self.window.cancel.assert_not_called()
        close_event.accept.assert_called_once_with()
        close_event.ignore.assert_not_called()
        self.window.thread = None


if __name__ == "__main__":
    unittest.main()
