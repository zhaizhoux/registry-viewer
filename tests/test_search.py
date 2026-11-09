import unittest

from regview.search import search
from tests.fake import FakeRegistry, sample_tree


class Cancelled:
    def is_set(self):
        return True


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry(sample_tree())

    def test_key_name(self):
        result = search(self.registry, "Acme", "HKCU", scope="keys")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["kind"], "key")
        self.assertTrue(result["results"][0]["path"].endswith("Acme"))

    def test_value_name_and_data(self):
        by_name = search(self.registry, "Wallpaper", "HKCU", scope="values")
        self.assertEqual(by_name["count"], 1)
        by_data = search(self.registry, "1.2.3", "HKCU", scope="values")
        self.assertEqual(by_data["count"], 1)
        self.assertEqual(by_data["results"][0]["name"], "Version")

    def test_scope_excludes(self):
        # Acme 既是子键名，也出现在 InstallPath 的值数据里，正好用来验证范围过滤
        keys_only = search(self.registry, "Acme", "HKCU", scope="keys")
        self.assertTrue(all(item["kind"] == "key" for item in keys_only["results"]))
        values_only = search(self.registry, "Acme", "HKCU", scope="values")
        self.assertGreater(values_only["count"], 0)
        self.assertTrue(all(item["kind"] == "value" for item in values_only["results"]))
        self.assertEqual(search(self.registry, "Wallpaper", "HKCU", scope="keys")["count"], 0)

    def test_case_insensitive(self):
        self.assertEqual(search(self.registry, "wallpaper", "HKCU")["count"], 1)

    def test_errors_are_tolerated(self):
        result = search(self.registry, "zzz-nothing", "HKCU")
        self.assertGreaterEqual(result["errors"], 1)
        self.assertGreater(result["scanned"], 3)

    def test_result_limit(self):
        result = search(self.registry, "e", "HKCU", limit=2)
        self.assertEqual(result["truncated"], "results")
        self.assertLessEqual(result["count"], 2)

    def test_time_limit(self):
        result = search(self.registry, "zzz-nothing", "HKCU", time_limit=0)
        self.assertEqual(result["truncated"], "time")

    def test_cancel(self):
        result = search(self.registry, "zzz-nothing", "HKCU", cancel=Cancelled())
        self.assertEqual(result["truncated"], "cancelled")

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            search(self.registry, "  ", "HKCU")
        with self.assertRaises(ValueError):
            search(self.registry, "x", "HKCU", scope="nothing")


if __name__ == "__main__":
    unittest.main()
