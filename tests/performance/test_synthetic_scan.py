import os
import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.prescan import scan_step


class PerformanceSmokeTest(unittest.TestCase):
    def test_many_records_streaming(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.ifc"
            with path.open("wb") as stream:
                for step_id in range(1, 20_001):
                    context = b"$" if step_id % 5000 == 0 else b"#9"
                    stream.write(b"#%d=IFCSHAPEREPRESENTATION(%s,'Body','X',(#2));\n" %
                                 (step_id, context))
            self.assertEqual(len(scan_step(path, chunk_size=4096)), 4)


if __name__ == "__main__":
    unittest.main()
