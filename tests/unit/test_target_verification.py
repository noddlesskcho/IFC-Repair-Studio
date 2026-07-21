import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.target_verification import verify_targeted_output


class TargetVerificationTests(unittest.TestCase):
    def test_verifies_envelope_and_exact_assignment(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out.ifc"
            path.write_bytes(
                b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"
                b"#10=IFCSHAPEREPRESENTATION(#26,'Body','SweptSolid',(#2));\n"
                b"ENDSEC;\nEND-ISO-10303-21;\n"
            )
            result = verify_targeted_output(path, {10: 26})
            self.assertTrue(result.passed)
            self.assertEqual(result.verified, 1)
            self.assertEqual(result.remaining, 0)

    def test_rejects_missing_footer_and_unset_target(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out.ifc"
            path.write_bytes(
                b"ISO-10303-21;\n#10=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#2));"
            )
            result = verify_targeted_output(path, {10: 26})
            self.assertFalse(result.passed)
            self.assertEqual(result.remaining, 1)
            self.assertFalse(result.footer_valid)


if __name__ == "__main__":
    unittest.main()
