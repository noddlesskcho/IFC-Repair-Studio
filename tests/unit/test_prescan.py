import tempfile
import unittest
from pathlib import Path

from ifc_context_repair.prescan import scan_step
from ifc_context_repair.step_patch import targeted_step_patch


class PrescanTests(unittest.TestCase):
    def _scan(self, body: bytes):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "case.ifc"
            path.write_bytes(body)
            return scan_step(path)

    def test_variants_multiline_and_case(self):
        data = (b"ISO-10303-21;\nDATA;\n"
                b"#1=ifcshaperepresentation( \n $ , 'Body','SweptSolid',(#2));\n"
                b"#3=IfCsHaPeRePrEsEnTaTiOn(#9,'Body','SweptSolid',(#2));\nENDSEC;")
        found = self._scan(data)
        self.assertEqual([c.step_id for c in found], [1])
        self.assertEqual(found[0].line_number, 3)

    def test_dollar_in_string_and_other_entity_are_ignored(self):
        data = (b"#1=IFCPROPERTYSINGLEVALUE('price $', $, $);\n"
                b"#2=IFCSHAPEREPRESENTATION(#8,'Body $ value','X',(#4));")
        self.assertEqual(self._scan(data), [])

    def test_semicolon_and_escaped_quote_in_string(self):
        data = (b"#1=IFCLABEL('a;don''t end');\n"
                b"#2=IFCSHAPEREPRESENTATION($,'Body','X',(#4));")
        self.assertEqual([c.step_id for c in self._scan(data)], [2])

    def test_patch_changes_only_confirmed_first_argument(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "in.ifc"
            output = Path(folder) / "out.ifc"
            original = (b"ISO-10303-21;\r\n#1=IFCLABEL('$');\r\n"
                        b"#22=IFCSHAPEREPRESENTATION( \r\n $ ,'Body','X',(#1));\r\nEND-ISO-10303-21;")
            source.write_bytes(original)
            self.assertEqual(targeted_step_patch(source, output, {22: 91}), 1)
            expected = original.replace(b" $ ,'Body'", b" #91 ,'Body'")
            self.assertEqual(output.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
