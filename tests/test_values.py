import unittest

from regview.values import (REG_BINARY, REG_DWORD, REG_EXPAND_SZ, REG_MULTI_SZ,
                            REG_QWORD, REG_SZ, describe_value, escape_reg_string,
                            hex_dump, reg_value_lines, type_name)


class TestDescribeValue(unittest.TestCase):
    def test_string(self):
        item = describe_value("Name", REG_SZ, "hello")
        self.assertEqual(item["type"], "REG_SZ")
        self.assertEqual(item["display"], "hello")
        self.assertEqual(item["size"], 5)

    def test_dword_qword(self):
        self.assertEqual(describe_value("n", REG_DWORD, 255)["display"], "0x000000FF (255)")
        self.assertEqual(describe_value("n", REG_QWORD, 4294967296)["display"],
                         "0x0000000100000000 (4294967296)")

    def test_multi_sz(self):
        item = describe_value("list", REG_MULTI_SZ, ["alpha", "beta"])
        self.assertEqual(item["display"], "alpha | beta")
        self.assertEqual(item["full"], "alpha\nbeta")

    def test_expand_sz(self):
        item = describe_value("p", REG_EXPAND_SZ, "%FAKE_REGVIEW_VAR%\\bin")
        self.assertIn("expanded", item)
        self.assertIsInstance(item["expanded"], str)

    def test_binary(self):
        item = describe_value("b", REG_BINARY, bytes(range(32)))
        self.assertIn("00 01 02", item["display"])
        self.assertIn("32 字节", item["display"])
        self.assertIn("00000010", item["hex"])
        self.assertIn("|................|", item["hex"])

    def test_default_name_and_unknown_type(self):
        self.assertEqual(describe_value("", REG_SZ, "x")["name"], "")
        self.assertEqual(type_name(999), "REG_UNKNOWN_999")

    def test_display_is_clipped(self):
        item = describe_value("long", REG_SZ, "x" * 500)
        self.assertTrue(item["display"].endswith("…"))
        self.assertEqual(len(item["full"]), 500)


class TestHexDump(unittest.TestCase):
    def test_offsets_and_ascii(self):
        text = hex_dump(b"ABC" + bytes(13), width=16)
        self.assertIn("00000000", text)
        self.assertIn("41 42 43", text)
        self.assertIn("|ABC", text)

    def test_large_input_is_capped(self):
        text = hex_dump(b"\x00" * 5000)
        self.assertIn("还有", text)


class TestRegSerialization(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(escape_reg_string('a"b\\c'), 'a\\"b\\\\c')

    def test_string_and_default_value(self):
        self.assertEqual(reg_value_lines("Name", REG_SZ, "hello"), ['"Name"="hello"'])
        self.assertEqual(reg_value_lines("", REG_SZ, "default"), ['@="default"'])

    def test_escaped_string(self):
        line = reg_value_lines("Quote", REG_SZ, 'path "C:\\temp"\\value')[0]
        self.assertTrue(line.startswith('"Quote"="'))
        self.assertIn('\\"', line)
        self.assertIn('\\\\', line)

    def test_dword_qword(self):
        self.assertEqual(reg_value_lines("D", REG_DWORD, 255), ['"D"=dword:000000ff'])
        self.assertEqual(reg_value_lines("Q", REG_QWORD, 4294967296),
                         ['"Q"=hex(b):00,00,00,00,01,00,00,00'])

    def test_expand_and_multi(self):
        self.assertTrue(reg_value_lines("E", REG_EXPAND_SZ, "%WINDIR%")[0]
                        .startswith('"E"=hex(2):'))
        self.assertTrue(reg_value_lines("M", REG_MULTI_SZ, ["a", "b"])[0]
                        .startswith('"M"=hex(7):'))

    def test_binary_continuation(self):
        lines = reg_value_lines("B", REG_BINARY, bytes(range(60)))
        self.assertGreater(len(lines), 2)
        self.assertTrue(lines[0].startswith('"B"=hex:'))
        self.assertTrue(lines[0].endswith("\\"))
        self.assertTrue(lines[1].startswith("  "))
        self.assertFalse(lines[-1].endswith("\\"))

    def test_empty_binary(self):
        self.assertEqual(reg_value_lines("B", REG_BINARY, b""), ['"B"=hex:'])

    def test_string_with_newline_uses_hex(self):
        self.assertTrue(reg_value_lines("S", REG_SZ, "a\nb")[0].startswith('"S"=hex(1):'))


if __name__ == "__main__":
    unittest.main()
