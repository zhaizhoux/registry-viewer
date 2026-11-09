import json
import tempfile
import unittest
from pathlib import Path

from regview.bookmarks import BookmarkStore


class TestBookmarks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = BookmarkStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_add_normalizes_and_deduplicates(self):
        items = self.store.add("hklm/software/microsoft")
        self.assertEqual(items[0]["path"], "HKEY_LOCAL_MACHINE\\software\\microsoft")
        self.assertEqual(items[0]["name"], "microsoft")
        again = self.store.add("HKLM\\SOFTWARE\\microsoft")  # 大小写不同但规范化后相同
        self.assertEqual(len(again), 1)

    def test_remove_and_clear(self):
        self.store.add("HKCU\\Software")
        self.store.add("HKLM\\SOFTWARE")
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(len(self.store.remove("HKCU\\Software")), 1)
        self.assertEqual(self.store.clear(), [])
        self.assertEqual(self.store.list(), [])

    def test_corrupt_file_is_tolerated(self):
        Path(self.store.file).parent.mkdir(parents=True, exist_ok=True)
        Path(self.store.file).write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.list(), [])
        self.assertEqual(len(self.store.add("HKCU")), 1)

    def test_file_is_valid_json(self):
        self.store.add("HKCU")
        payload = json.loads(Path(self.store.file).read_text(encoding="utf-8"))
        self.assertEqual(payload[0]["path"], "HKEY_CURRENT_USER")


if __name__ == "__main__":
    unittest.main()
