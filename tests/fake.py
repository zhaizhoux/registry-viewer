"""内存版注册表，用于跨平台单元测试和 HTTP 服务测试。

数据结构：
    { "HKCU\\Software": {"values": [(name, type_id, data)], "children": [str], "error": {...}} }
路径可以用根键缩写，FakeRegistry 会先规范化。
"""

from __future__ import annotations

from typing import Any, Dict, List

from regview.paths import normalize_path, parent_path, root_list
from regview.values import describe_value


class FakeRegistry:
    def __init__(self, tree: Dict[str, Dict[str, Any]]):
        self.tree = {normalize_path(path): node for path, node in tree.items()}

    def roots(self) -> List[dict]:
        return root_list()

    def _get(self, path: str) -> Dict[str, Any]:
        return self.tree.get(normalize_path(path))

    def _children(self, path: str) -> List[str]:
        node = self._get(path)
        return list(node.get("children", [])) if node else []

    def _values(self, path: str):
        node = self._get(path)
        return list(node.get("values", [])) if node else []

    def _error(self, path: str):
        node = self._get(path)
        if node is None:
            return {"message": "键不存在", "path": path, "winerror": 2}
        if node.get("error"):
            return {"message": node["error"], "path": path, "winerror": 5}
        return None

    def children(self, path: str) -> Dict[str, Any]:
        normalized = normalize_path(path)
        return {
            "path": normalized,
            "children": self._children(normalized),
            "error": self._error(normalized),
            "truncated": False,
        }

    def node(self, path: str) -> Dict[str, Any]:
        normalized = normalize_path(path)
        error = self._error(normalized)
        return {
            "path": normalized,
            "parent": parent_path(normalized),
            "subkeys": [] if error else self._children(normalized),
            "values": [] if error else [
                describe_value(name, type_id, data)
                for name, type_id, data in self._values(normalized)
            ],
            "error": error,
            "truncated": False,
        }

    def value_detail(self, path: str, name: str) -> Dict[str, Any]:
        normalized = normalize_path(path)
        for value_name, type_id, data in self._values(normalized):
            if value_name == name:
                detail = describe_value(value_name, type_id, data)
                detail["path"] = normalized
                return detail
        raise KeyError("没有这个值：%r" % name)

    def walk(self, path: str, max_keys: int = 2000):
        root = normalize_path(path)
        stack = [root]
        visited = 0
        while stack and visited < max_keys:
            current = stack.pop()
            visited += 1
            error = self._error(current)
            subkeys = [] if error else self._children(current)
            raw_values = [] if error else self._values(current)
            yield {
                "path": current,
                "error": error,
                "subkeys": subkeys,
                "values": [describe_value(n, t, d) for n, t, d in raw_values],
                "raw_values": raw_values,
            }
            for child in reversed(subkeys):
                stack.append(current + "\\" + child)


def sample_tree() -> Dict[str, Dict[str, Any]]:
    from regview.values import (REG_BINARY, REG_DWORD, REG_EXPAND_SZ,
                                REG_MULTI_SZ, REG_QWORD, REG_SZ)
    return {
        "HKCU": {"children": ["Software", "Control Panel"], "values": [
            ("", REG_SZ, "默认值内容"),
        ]},
        "HKCU\\Software": {"children": ["Acme", "Missing"], "values": [
            ("Version", REG_SZ, "1.2.3"),
        ]},
        "HKCU\\Software\\Acme": {"children": [], "values": [
            ("InstallPath", REG_EXPAND_SZ, "%ProgramFiles%\\Acme"),
            ("Enabled", REG_DWORD, 1),
            ("BigNumber", REG_QWORD, 4294967296),
            ("Names", REG_MULTI_SZ, ["alpha", "beta"]),
            ("Blob", REG_BINARY, bytes(range(32))),
            ("Quote", REG_SZ, 'path "C:\\temp"\\value'),
        ]},
        "HKCU\\Software\\Missing": {"error": "拒绝访问", "children": [], "values": []},
        "HKCU\\Control Panel": {"children": ["Desktop"], "values": []},
        "HKCU\\Control Panel\\Desktop": {"children": [], "values": [
            ("Wallpaper", REG_SZ, "C:\\wall.png"),
        ]},
        "HKLM": {"children": ["SOFTWARE"], "values": []},
        "HKLM\\SOFTWARE": {"children": [], "values": [
            ("ProductName", REG_SZ, "Windows"),
        ]},
    }
