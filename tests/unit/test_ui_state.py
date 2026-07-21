import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
        self.assertTrue(self.window.scan_button.isEnabled())
        self.assertEqual(self.window.scan_button.objectName(), "primary")
        self.assertFalse(self.window.repair_button.isEnabled())

    def test_repair_becomes_primary_after_issues_found(self):
        self.window.report = RunReport(
            source="sample.ifc",
            summary_counts={"AutomaticallyRepairable": 3151, "ElementsAffected": 2051},
        )
        self.window._apply_state(WorkflowState.ISSUES_FOUND)
        self.assertEqual(self.window.repair_button.objectName(), "primary")
        self.assertEqual(self.window.scan_button.objectName(), "")
        self.assertEqual(self.window.scan_button.text(), "Scan Again")
        self.assertIn("3,151", self.window.repair_button.text())

    def test_no_repair_action_when_no_issues(self):
        self.window._apply_state(WorkflowState.NO_ISSUES)
        self.assertTrue(self.window.repair_button.isHidden())

    def test_simplified_ui_has_no_theme_or_folder_controls(self):
        self.assertFalse(hasattr(self.window, "theme_button"))
        self.assertFalse(hasattr(self.window, "open_source_folder_button"))
        self.assertFalse(hasattr(self.window, "output_folder_button"))

    def test_completion_uses_compact_report_menu(self):
        labels = [action.text() for action in self.window.report_menu.actions()]
        self.assertIn("HTML Engineering Report", labels)
        self.assertIn("PDF Executive Report", labels)
        self.assertIn("Open Repaired IFC", labels)


if __name__ == "__main__":
    unittest.main()
