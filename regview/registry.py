"""winreg 的只读封装。

安全约束（重要）：本模块所有打开操作都使用 ``KEY_READ``，
不调用任何 SetValue / CreateKey / DeleteKey / DeleteValue 等写入 API，
因此这个查看器在物理上无法修改注册表。
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .paths import normalize_path, parent_path, parse_path, root_list
from .values import describe_value

try:  # pragma: no cover - 平台相关
    import winreg
except ImportError:  # pragma: no cover - Linux/macOS
    winreg = None  # type: ignore[assignment]

MAX_SUBKEYS = 10000
MAX_VALUES = 5000

_VIEW_FLAGS = {"default": 0, "64": 0x0100, "32": 0x0200}  # KEY_WOW64_64KEY / _32KEY
_VALID_VIEWS = tuple(_VIEW_FLAGS)


class RegistryError(Exception):
    """读取注册表失败（权限不足、键不存在等）。"""

    def __init__(self, message: str, path: str = "", winerror: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.path = path
        self.winerror = winerror

    def to_dict(self) -> Dict[str, Any]:
        return {"message": self.message, "path": self.path, "winerror": self.winerror}


def _friendly_error(exc: OSError, path: str) -> RegistryError:
    code = getattr(exc, "winerror", None)
    if code == 5 or (code is None and "denied" in str(exc).lower()):
        message = "拒绝访问：该键受系统保护，或需要管理员权限"
    elif code == 2 or (code is None and "not found" in str(exc).lower()):
        message = "键不存在或已被删除"
    else:
        message = "读取失败：%s" % exc
    return RegistryError(message, path, code)


class Registry:
    """只读注册表访问对象。view 可选 default / 64 / 32（WOW64 视图）。"""

    def __init__(self, view: str = "default"):
        if winreg is None:
            raise RegistryError("regview 需要 Windows 的 winreg 模块（当前平台：%s）" % sys.platform)
        if view not in _VALID_VIEWS:
            raise RegistryError("未知注册表视图 %r，可用：default / 64 / 32" % view)
        self.view = view
        # 唯一允许的权限位：只读。加上视图标志即可切换 32/64 位视图。
        self.access = winreg.KEY_READ | _VIEW_FLAGS[view]

    def roots(self) -> List[dict]:
        return root_list()

    def _open(self, path: str):
        normalized = normalize_path(path)
        root_name, sub = parse_path(normalized)
        handle = getattr(winreg, root_name)
        try:
            return winreg.OpenKey(handle, sub, 0, self.access)
        except OSError as exc:
            raise _friendly_error(exc, normalized) from exc

    def _read(self, path: str) -> Tuple[List[str], List[Tuple[str, int, Any]]]:
        """打开一次键，返回 (子键名列表, 原始值三元组列表)。"""
        normalized = normalize_path(path)
        key = self._open(normalized)
        try:
            subkey_count, value_count, _modified = winreg.QueryInfoKey(key)
            subkeys: List[str] = []
            for index in range(min(subkey_count, MAX_SUBKEYS)):
                try:
                    subkeys.append(winreg.EnumKey(key, index))
                except OSError:
                    break
            raw_values: List[Tuple[str, int, Any]] = []
            for index in range(min(value_count, MAX_VALUES)):
                try:
                    name, data, type_id = winreg.EnumValue(key, index)
                    raw_values.append((name, type_id, data))
                except OSError:
                    break
            return subkeys, raw_values
        finally:
            winreg.CloseKey(key)

    def children(self, path: str) -> Dict[str, Any]:
        """懒加载树节点：只列子键名，不读取值。"""
        normalized = normalize_path(path)
        try:
            subkeys, _ = self._read(normalized)
        except RegistryError as exc:
            return {"path": normalized, "children": [], "error": exc.to_dict(), "truncated": False}
        return {
            "path": normalized,
            "children": subkeys,
            "error": None,
            "truncated": False,
        }

    def node(self, path: str) -> Dict[str, Any]:
        """给主界面用的一次性数据：子键 + 值 + 父键 + 错误。"""
        normalized = normalize_path(path)
        try:
            subkeys, raw_values = self._read(normalized)
        except RegistryError as exc:
            return {
                "path": normalized,
                "parent": parent_path(normalized),
                "subkeys": [],
                "values": [],
                "error": exc.to_dict(),
                "truncated": False,
            }
        values = [describe_value(name, type_id, data) for name, type_id, data in raw_values]
        return {
            "path": normalized,
            "parent": parent_path(normalized),
            "subkeys": subkeys,
            "values": values,
            "error": None,
            "truncated": False,
        }

    def value_detail(self, path: str, name: str) -> Dict[str, Any]:
        """读取单个值的完整内容（含二进制 hex dump）。"""
        normalized = normalize_path(path)
        _subkeys, raw_values = self._read(normalized)
        for value_name, type_id, data in raw_values:
            if value_name == name:
                detail = describe_value(value_name, type_id, data)
                detail["path"] = normalized
                return detail
        raise RegistryError("该键下没有名为 %r 的值" % name, normalized)

    def walk(self, path: str, max_keys: int = 2000) -> Iterator[Dict[str, Any]]:
        """深度优先遍历子键，遇到拒绝访问会记录并继续，不中断整次遍历。"""
        root = normalize_path(path)
        stack = [root]
        visited = 0
        while stack and visited < max_keys:
            current = stack.pop()
            visited += 1
            try:
                subkeys, raw_values = self._read(current)
            except RegistryError as exc:
                yield {"path": current, "error": exc.to_dict(), "subkeys": [],
                       "values": [], "raw_values": []}
                continue
            yield {
                "path": current,
                "error": None,
                "subkeys": subkeys,
                "values": [describe_value(n, t, d) for n, t, d in raw_values],
                # 导出 .reg 需要原始字节/整数，不能用展示字符串代替
                "raw_values": raw_values,
            }
            # 反序压栈，保证界面上看到的顺序与 regedit 一致
            for child in reversed(subkeys):
                stack.append(current + "\\" + child)
