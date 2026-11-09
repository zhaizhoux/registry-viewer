"""真机只读冒烟测试：只在 Windows 上执行，绝不写入注册表。"""

import sys
import unittest

from regview.export import build_export
from regview.registry import Registry
from regview.search import search


@unittest.skipUnless(sys.platform == "win32", "需要 Windows 注册表")
class TestRealRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()

    def test_roots_and_current_user(self):
        self.assertEqual(len(self.registry.roots()), 5)
        node = self.registry.node("HKEY_CURRENT_USER")
        self.assertIsNone(node["error"])
        self.assertGreater(len(node["subkeys"]), 0)

    def test_known_system_value(self):
        detail = self.registry.value_detail(
            "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "ProductName",
        )
        self.assertEqual(detail["type"], "REG_SZ")
        self.assertIn("Windows", detail["full"])

    def test_wow64_views(self):
        for view in ("64", "32"):
            node = Registry(view).node("HKLM\\SOFTWARE")
            self.assertIsNone(node["error"], view)

    def test_missing_key_returns_error(self):
        node = self.registry.node("HKCU\\Software\\__regview_no_such_key__")
        self.assertIsNotNone(node["error"])
        self.assertEqual(node["values"], [])

    def test_children_lazy_load(self):
        data = self.registry.children("HKCU\\Software")
        self.assertIsNone(data["error"])
        self.assertIsInstance(data["children"], list)

    def test_walk_is_bounded(self):
        items = list(self.registry.walk("HKCU\\Software\\Microsoft", max_keys=12))
        self.assertLessEqual(len(items), 12)
        self.assertTrue(all("path" in item for item in items))

    def test_search_real_registry(self):
        result = search(self.registry, "Windows", "HKLM\\SOFTWARE\\Microsoft\\Windows NT",
                        limit=10, max_keys=60, time_limit=2.0)
        self.assertIn("scanned", result)
        self.assertLessEqual(result["count"], 10)

    def test_export_real_key(self):
        result = build_export(
            self.registry, "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",
            "json", max_keys=1,
        )
        self.assertIn('"readonly": true', result["text"])


if __name__ == "__main__":
    unittest.main()
