import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ifc_context_repair.naming import default_repaired_path, overwrite_backup_path


class OutputNamingTests(unittest.TestCase):
    def test_default_output_and_collision_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.ifc"
            source.touch()
            self.assertEqual(default_repaired_path(source).name, "sample_repaired.ifc")
            (Path(folder) / "sample_repaired.ifc").touch()
            self.assertEqual(default_repaired_path(source).name, "sample_repaired_2.ifc")

    def test_backup_never_appends_backup_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample_backup.ifc"
            source.touch()
            first = overwrite_backup_path(source)
            self.assertEqual(first.name, "sample_backup.original.ifc")
            first.touch()
            second = overwrite_backup_path(source, datetime(2026, 7, 19, 14, 30, 15))
            self.assertEqual(
                second.name, "sample_backup.original_20260719_143015.ifc"
            )
            self.assertNotIn("backup_backup", second.name)


if __name__ == "__main__":
    unittest.main()
