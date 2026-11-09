"""静态安全约束：确保查看器在物理上没有写入注册表的能力。"""

import ast
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "regview"
FORBIDDEN_CALLS = {
    "SetValue", "SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey",
    "DeleteKeyEx", "DeleteValue", "SaveKey", "ReplaceKey", "RestoreKey",
    "RegSetValue", "RegDeleteKey", "ConnectRegistry",
}


class TestReadOnly(unittest.TestCase):
    def test_no_write_api_calls_in_source(self):
        for source in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = ""
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                self.assertNotIn(name, FORBIDDEN_CALLS,
                                 "%s 中出现了写入调用 %s" % (source.name, name))

    def test_open_uses_key_read(self):
        source = (PACKAGE / "registry.py").read_text(encoding="utf-8")
        self.assertIn("winreg.KEY_READ", source)
        self.assertIn("self.access = winreg.KEY_READ |", source)

    @unittest.skipUnless(sys.platform == "win32", "仅 Windows 有 winreg")
    def test_access_flag_has_no_write_bits(self):
        import winreg
        from regview.registry import Registry
        write_bits = winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY
        for view in ("default", "64", "32"):
            self.assertEqual(Registry(view).access & write_bits, 0)

    def test_server_refuses_non_local_bind(self):
        from regview.server import create_server
        for host in ("0.0.0.0", "192.168.1.2", "github.com"):
            with self.assertRaises(ValueError):
                create_server(host=host)

    def test_frontend_has_no_external_resources(self):
        web = PACKAGE / "web"
        patterns = ('src="http', 'href="http', '@import url(http', 'fetch("http')
        for asset in sorted(web.iterdir()):
            if asset.suffix not in (".html", ".js", ".css", ".svg"):
                continue
            text = asset.read_text(encoding="utf-8")
            for pattern in patterns:
                self.assertNotIn(pattern, text, "%s 含外部资源 %s" % (asset.name, pattern))


if __name__ == "__main__":
    unittest.main()
