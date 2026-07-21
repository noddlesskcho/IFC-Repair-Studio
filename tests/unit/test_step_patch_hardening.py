import os
import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.change_audit import audit_targeted_changes
from ifc_context_repair.errors import OutputError
from ifc_context_repair.output_safety import preflight_output
from ifc_context_repair.step_patch import (
    PatchEdit, PatchPlan, apply_patch_plan, build_patch_plan, source_fingerprint,
    validate_patch_plan,
)
from ifc_context_repair.target_verification import verify_targeted_output


def ifc(*records: bytes, newline: bytes = b"\n") -> bytes:
    return newline.join((
        b"ISO-10303-21;", b"HEADER;", b"ENDSEC;", b"DATA;", *records,
        b"ENDSEC;", b"END-ISO-10303-21;", b"",
    ))


class StepPatchHardeningTests(unittest.TestCase):
    def _apply(self, data: bytes, replacements: dict[int, int]):
        folder = tempfile.TemporaryDirectory()
        source = Path(folder.name) / "source.ifc"
        output = Path(folder.name) / "output.ifc"
        source.write_bytes(data)
        plan = build_patch_plan(source, replacements)
        validate_patch_plan(plan)
        result = apply_patch_plan(plan, output)
        return folder, source, output, plan, result

    def test_variable_length_context_references_and_crlf(self):
        original = ifc(
            b"#10=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#2));",
            b"#11=IFCSHAPEREPRESENTATION($,'FootPrint','Curve2D',(#3));",
            newline=b"\r\n",
        )
        folder, source, output, _, _ = self._apply(original, {10: 26, 11: 123456})
        try:
            repaired = output.read_bytes()
            self.assertIn(b"IFCSHAPEREPRESENTATION(#26,'Body'", repaired)
            self.assertIn(b"IFCSHAPEREPRESENTATION(#123456,'FootPrint'", repaired)
            self.assertEqual(source.read_bytes(), original)
        finally:
            folder.cleanup()

    def test_multiline_whitespace_lowercase_and_semicolon_in_string(self):
        data = ifc(
            b"#7=IFCLABEL('do not end; here');",
            b"#42 = ifcshaperepresentation (\r\n  $ , 'Body','SweptSolid',(#7));",
        )
        folder, _, output, plan, result = self._apply(data, {42: 900001})
        try:
            verification = verify_targeted_output(
                output, {42: 900001}, source=plan.source, plan=plan, write_result=result
            )
            self.assertTrue(verification.passed, verification.messages)
            self.assertTrue(verification.records_unchanged_except_context)
        finally:
            folder.cleanup()

    def test_duplicate_step_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "duplicate.ifc"
            source.write_bytes(ifc(
                b"#10=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#2));",
                b"#10=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#3));",
            ))
            with self.assertRaisesRegex(OutputError, "Duplicate"):
                build_patch_plan(source, {10: 26})

    def test_invalid_and_overlapping_patch_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ifc"
            source.write_bytes(ifc(b"#10=IFCSHAPEREPRESENTATION($,'Body','X',(#2));"))
            fingerprint = source_fingerprint(source)
            edits = (
                PatchEdit(10, 26, 20, 22, 10, 50, b"#26"),
                PatchEdit(11, 27, 21, 23, 10, 50, b"#27"),
            )
            with self.assertRaisesRegex(OutputError, "Overlapping"):
                validate_patch_plan(PatchPlan(source, fingerprint, edits, fingerprint.size + 2))
            with self.assertRaises(OutputError):
                build_patch_plan(source, {0: 26})

    def test_missing_expected_unset_token_and_missing_id_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ifc"
            source.write_bytes(ifc(b"#10=IFCSHAPEREPRESENTATION(#8,'Body','X',(#2));"))
            with self.assertRaisesRegex(OutputError, "no longer has an unset context"):
                build_patch_plan(source, {10: 26})
            with self.assertRaisesRegex(OutputError, "Could not locate"):
                build_patch_plan(source, {999: 26})

    def test_source_modified_after_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ifc"
            output = Path(folder) / "output.ifc"
            source.write_bytes(ifc(b"#10=IFCSHAPEREPRESENTATION($,'Body','X',(#2));"))
            plan = build_patch_plan(source, {10: 26})
            with source.open("ab") as stream:
                stream.write(b" ")
                stream.flush()
                os.fsync(stream.fileno())
            with self.assertRaisesRegex(OutputError, "changed"):
                apply_patch_plan(plan, output)

    def test_change_audit_detects_unexpected_record_edit(self):
        data = ifc(
            b"#9=IFCLABEL('original');",
            b"#10=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#2));",
        )
        folder, source, output, plan, result = self._apply(data, {10: 26})
        try:
            passed = audit_targeted_changes(source, output, plan, result)
            self.assertTrue(passed.passed)
            changed = output.read_bytes().replace(b"original", b"modified", 1)
            output.write_bytes(changed)
            failed = audit_targeted_changes(source, output, plan, result)
            self.assertFalse(failed.passed)
            self.assertGreater(failed.unexpected_modified_records, 0)
        finally:
            folder.cleanup()

    def test_wrong_context_and_truncated_output_are_detected(self):
        data = ifc(b"#10=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#2));")
        folder, source, output, plan, result = self._apply(data, {10: 26})
        try:
            output.write_bytes(output.read_bytes().replace(b"#26,'Body'", b"#99,'Body'"))
            wrong = verify_targeted_output(
                output, {10: 26}, source=source, plan=plan, write_result=result
            )
            self.assertFalse(wrong.passed)
            output.write_bytes(output.read_bytes().split(b"END-ISO")[0])
            truncated = verify_targeted_output(output, {10: 26})
            self.assertFalse(truncated.footer_valid)
        finally:
            folder.cleanup()

    def test_unavailable_output_directory_fails_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ifc"
            source.write_bytes(ifc(b"#10=IFCSHAPEREPRESENTATION($,'Body','X',(#2));"))
            with self.assertRaisesRegex(OutputError, "does not exist"):
                preflight_output(source, Path(folder) / "missing" / "out.ifc", replace_original=False)


if __name__ == "__main__":
    unittest.main()
