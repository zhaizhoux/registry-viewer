import json
import unittest

from regview.export import FORMATS, build_export
from tests.fake import FakeRegistry, sample_tree


class TestExport(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry(sample_tree())
        self.root = "HKCU\\Software"

    def test_reg(self):
        result = build_export(self.registry, self.root, "reg")
        self.assertEqual(result["encoding"], "utf-16")
        self.assertTrue(result["filename"].endswith(".reg"))
        text = result["text"]
        self.assertTrue(text.startswith("Windows Registry Editor Version 5.00"))
        self.assertIn("[HKEY_CURRENT_USER\\Software]", text)
        self.assertIn("[HKEY_CURRENT_USER\\Software\\Acme]", text)
        self.assertIn('"Version"="1.2.3"', text)
        self.assertIn('"Enabled"=dword:00000001', text)
        self.assertIn('"BigNumber"=hex(b):00,00,00,00,01,00,00,00', text)
        self.assertIn("; 跳过", text)
        self.assertEqual(result["stats"]["errors"], 1)
        self.assertEqual(result["stats"]["keys"], 2)
        self.assertIn("\r\n", text)
        # utf-16 编码必须带 BOM，否则 regedit 无法正确识别
        self.assertTrue(text.encode("utf-16").startswith(b"\xff\xfe"))

    def test_json(self):
        result = build_export(self.registry, self.root, "json")
        payload = json.loads(result["text"])
        self.assertTrue(payload["readonly"])
        self.assertEqual(payload["root"], "HKEY_CURRENT_USER\\Software")
        self.assertEqual(len(payload["keys"]), 3)
        self.assertEqual(result["encoding"], "utf-8")
        acme = next(k for k in payload["keys"] if k["path"].endswith("Acme"))
        self.assertEqual(len(acme["values"]), 6)

    def test_csv(self):
        result = build_export(self.registry, self.root, "csv")
        lines = result["text"].splitlines()
        self.assertEqual(lines[0], "key_path,value_name,type,data,size_bytes")
        self.assertTrue(any("InstallPath" in line for line in lines))
        self.assertEqual(result["encoding"], "utf-8-sig")

    def test_default_value_is_named(self):
        result = build_export(self.registry, "HKCU", "reg")
        self.assertIn('@="默认值内容"', result["text"])

    def test_invalid_format(self):
        with self.assertRaises(ValueError):
            build_export(self.registry, self.root, "xml")
        self.assertEqual(tuple(FORMATS), ("reg", "json", "csv"))

    def test_max_keys_truncation(self):
        result = build_export(self.registry, self.root, "reg", max_keys=2)
        self.assertTrue(result["stats"]["truncated"])


if __name__ == "__main__":
    unittest.main()
