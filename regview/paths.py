"""注册表路径解析与规范化。

这一层是纯字符串逻辑，不导入 winreg，因此在任何平台上都可测试。
Windows 注册表键名不允许包含反斜杠，所以用 ``\\`` 切分路径是安全的。
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional, Tuple


class PathError(ValueError):
    """路径不是合法的注册表路径。"""


class RootKey(NamedTuple):
    name: str
    alias: str
    handle: int
    description: str


ROOT_KEYS: Tuple[RootKey, ...] = (
    RootKey("HKEY_CLASSES_ROOT", "HKCR", 0x80000000, "文件关联与 COM 组件注册"),
    RootKey("HKEY_CURRENT_USER", "HKCU", 0x80000001, "当前登录用户配置"),
    RootKey("HKEY_LOCAL_MACHINE", "HKLM", 0x80000002, "本机全局配置"),
    RootKey("HKEY_USERS", "HKU", 0x80000003, "所有用户配置单元"),
    RootKey("HKEY_CURRENT_CONFIG", "HKCC", 0x80000005, "当前硬件配置文件"),
)

_BY_NAME = {item.name.upper(): item for item in ROOT_KEYS}
_BY_ALIAS = {item.alias.upper(): item for item in ROOT_KEYS}


def root_list() -> List[dict]:
    """给前端使用的根键元数据。"""
    return [
        {
            "name": item.name,
            "alias": item.alias,
            "description": item.description,
            "short": item.alias,
        }
        for item in ROOT_KEYS
    ]


def resolve_root(text: str) -> Optional[RootKey]:
    """把 ``HKLM`` / ``hkey_local_machine`` 之类的写法解析成根键。"""
    key = (text or "").strip().upper()
    return _BY_NAME.get(key) or _BY_ALIAS.get(key)


def _segments(text: str) -> List[str]:
    cleaned = (text or "").strip().strip('"').replace("/", "\\")
    return [part.strip() for part in cleaned.split("\\") if part.strip()]


def normalize_path(text: str) -> str:
    """把任意别名/斜杠/多余分隔符的路径规范化为 ``HKEY_...\\Sub\\Key``。

    >>> normalize_path("hklm/software/microsoft//windows")
    'HKEY_LOCAL_MACHINE\\software\\microsoft\\windows'
    """
    parts = _segments(text)
    if not parts:
        raise PathError("路径为空")
    root = resolve_root(parts[0])
    if root is None:
        raise PathError("未知根键 %r，可用：%s" % (parts[0], ", ".join(i.alias for i in ROOT_KEYS)))
    return "\\".join([root.name] + parts[1:])


def parse_path(path: str) -> Tuple[str, str]:
    """返回 ``(根键全名, 子路径)``；子路径为空表示根键本身。"""
    normalized = normalize_path(path)
    parts = normalized.split("\\")
    return parts[0], "\\".join(parts[1:])


def parent_path(path: str) -> Optional[str]:
    """父键路径；已经是根键时返回 None。"""
    normalized = normalize_path(path)
    parts = normalized.split("\\")
    if len(parts) <= 1:
        return None
    return "\\".join(parts[:-1])


def join_path(path: str, child: str) -> str:
    """拼接子键名（子键名中不允许出现反斜杠）。"""
    normalized = normalize_path(path)
    name = (child or "").strip().replace("/", "\\")
    if not name or "\\" in name:
        raise PathError("非法子键名 %r" % child)
    return normalized + "\\" + name


def is_root(path: str) -> bool:
    return "\\" not in normalize_path(path)


def shorten_path(path: str, max_len: int = 92) -> str:
    """地址栏/树节点用的紧凑显示：缩写根键，过长时保留尾段。"""
    normalized = normalize_path(path)
    root, sub = parse_path(normalized)
    short = _BY_NAME[root.upper()].alias
    display = short if not sub else short + "\\" + sub
    if len(display) <= max_len:
        return display
    tail = display[-(max_len - 3):]
    return "..." + tail


def leaf_name(path: str) -> str:
    """返回最后一段键名；根键返回缩写。"""
    normalized = normalize_path(path)
    parts = normalized.split("\\")
    if len(parts) == 1:
        return _BY_NAME[parts[0].upper()].alias
    return parts[-1]
