import json
import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.diagnostics import DiagnosticLogger


class DiagnosticLoggerTests(unittest.TestCase):
    def test_disabled_logger_keeps_event_in_memory_without_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample_repair_debug.log"
            logger = DiagnosticLogger(
                path, enabled=False, source=Path("sample.ifc"),
                output=Path("sample_repaired.ifc"),
            )
            event = logger.write("scan", "completed", duration=1.25)
            self.assertEqual(event["stage"], "scan")
            self.assertFalse(path.exists())

    def test_enabled_logger_writes_structured_event(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample_repair_debug.log"
            logger = DiagnosticLogger(
                path, enabled=True, source=Path("sample.ifc"),
                output=Path("sample_repaired.ifc"),
            )
            logger.write("verification", "completed", duration=.01)
            event = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(event["stage"], "verification")
            self.assertIn("thread", event)
            self.assertIn("memory_bytes", event)


if __name__ == "__main__":
    unittest.main()
