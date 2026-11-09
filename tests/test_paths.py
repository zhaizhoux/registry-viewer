import unittest

from regview.paths import (PathError, is_root, join_path, leaf_name,
                           normalize_path, parent_path, parse_path,
                           resolve_root, root_list, shorten_path)


class TestPaths(unittest.TestCase):
    def test_normalize_alias_and_separators(self):
        self.assertEqual(
            normalize_path("hklm/software/microsoft//windows"),
            "HKEY_LOCAL_MACHINE\\software\\microsoft\\windows",
        )
        self.assertEqual(normalize_path(' "HKCU\\Software\\" '), "HKEY_CURRENT_USER\\Software")

    def test_all_aliases(self):
        for item in root_list():
            self.assertEqual(normalize_path(item["alias"]), item["name"])
            self.assertEqual(normalize_path(item["name"].lower()), item["name"])

    def test_parse_and_parent(self):
        self.assertEqual(parse_path("HKCU\\Software\\Acme"),
                         ("HKEY_CURRENT_USER", "Software\\Acme"))
        self.assertEqual(parse_path("HKLM"), ("HKEY_LOCAL_MACHINE", ""))
        self.assertEqual(parent_path("HKCU\\Software\\Acme"), "HKEY_CURRENT_USER\\Software")
        self.assertIsNone(parent_path("HKCU"))

    def test_join_and_leaf(self):
        self.assertEqual(join_path("HKCU\\Software", "Acme"),
                         "HKEY_CURRENT_USER\\Software\\Acme")
        self.assertEqual(leaf_name("HKCU\\Software\\Acme"), "Acme")
        self.assertEqual(leaf_name("HKLM"), "HKLM")
        self.assertTrue(is_root("HKLM"))
        self.assertFalse(is_root("HKLM\\SOFTWARE"))

    def test_shorten(self):
        self.assertEqual(shorten_path("HKEY_CURRENT_USER\\Software"), "HKCU\\Software")
        long_path = "HKCU\\" + "\\".join("Segment%02d" % i for i in range(20))
        self.assertTrue(shorten_path(long_path).startswith("..."))

    def test_resolve_root_unknown(self):
        self.assertIsNone(resolve_root("NOPE"))
        for bad in ("", "Software\\Acme", "HKEY_NOPE\\Sub"):
            with self.assertRaises(PathError):
                normalize_path(bad)
        with self.assertRaises(PathError):
            join_path("HKCU", "a\\b")


if __name__ == "__main__":
    unittest.main()
