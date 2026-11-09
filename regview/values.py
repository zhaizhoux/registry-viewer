"""注册表值的类型识别、展示与 .reg 文件序列化。

类型编号与 winreg 常量一致，这里硬编码以便在没有 winreg 的平台上测试。
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional

REG_NONE = 0
REG_SZ = 1
REG_EXPAND_SZ = 2
REG_BINARY = 3
REG_DWORD = 4
REG_DWORD_BIG_ENDIAN = 5
REG_LINK = 6
REG_MULTI_SZ = 7
REG_RESOURCE_LIST = 8
REG_FULL_RESOURCE_DESCRIPTOR = 9
REG_RESOURCE_REQUIREMENTS_LIST = 10
REG_QWORD = 11

TYPE_NAMES: Dict[int, str] = {
    REG_NONE: "REG_NONE",
    REG_SZ: "REG_SZ",
    REG_EXPAND_SZ: "REG_EXPAND_SZ",
    REG_BINARY: "REG_BINARY",
    REG_DWORD: "REG_DWORD",
    REG_DWORD_BIG_ENDIAN: "REG_DWORD_BIG_ENDIAN",
    REG_LINK: "REG_LINK",
    REG_MULTI_SZ: "REG_MULTI_SZ",
    REG_RESOURCE_LIST: "REG_RESOURCE_LIST",
    REG_FULL_RESOURCE_DESCRIPTOR: "REG_FULL_RESOURCE_DESCRIPTOR",
    REG_RESOURCE_REQUIREMENTS_LIST: "REG_RESOURCE_REQUIREMENTS_LIST",
    REG_QWORD: "REG_QWORD",
}

DISPLAY_LIMIT = 260
HEX_PREVIEW_BYTES = 32
HEX_DUMP_BYTES = 2048


def type_name(type_id: int) -> str:
    return TYPE_NAMES.get(type_id, "REG_UNKNOWN_%d" % type_id)


def _clip(text: str, limit: int = DISPLAY_LIMIT) -> str:
    text = text.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def hex_dump(data: bytes, width: int = 16, max_bytes: int = HEX_DUMP_BYTES) -> str:
    """带偏移与 ASCII 列的十六进制视图。"""
    if not isinstance(data, (bytes, bytearray)):
        return ""
    chunk = bytes(data[:max_bytes])
    lines = []
    for offset in range(0, len(chunk), width):
        part = chunk[offset:offset + width]
        hex_part = " ".join("%02X" % byte for byte in part)
        ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in part)
        lines.append("%08X  %-47s  |%s|" % (offset, hex_part, ascii_part))
    if len(data) > max_bytes:
        lines.append("... 还有 %d 字节未显示" % (len(data) - max_bytes))
    return "\n".join(lines)


def _hex_preview(data: bytes) -> str:
    head = bytes(data[:HEX_PREVIEW_BYTES])
    text = " ".join("%02X" % byte for byte in head)
    if len(data) > HEX_PREVIEW_BYTES:
        text += " …"
    return "%s  (%d 字节)" % (text, len(data))


def _byte_size(data: Any) -> int:
    if isinstance(data, (bytes, bytearray)):
        return len(data)
    if isinstance(data, str):
        return len(data.encode("utf-8", errors="replace"))
    if isinstance(data, (list, tuple)):
        return sum(_byte_size(item) for item in data)
    if isinstance(data, int):
        return 8
    return len(str(data))


def describe_value(name: str, type_id: int, data: Any) -> Dict[str, Any]:
    """把 winreg.EnumValue 的三元组转成前端可直接渲染的结构。"""
    result: Dict[str, Any] = {
        "name": name,
        "type": type_name(type_id),
        "type_id": type_id,
        "size": _byte_size(data),
        "display": "",
        "full": "",
        "hex": None,
        "expanded": None,
    }

    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
        result["display"] = _hex_preview(raw)
        result["full"] = _hex_preview(raw)
        result["hex"] = hex_dump(raw)
    elif type_id == REG_DWORD:
        value = int(data) & 0xFFFFFFFF
        text = "0x%08X (%d)" % (value, value)
        result["display"] = result["full"] = text
    elif type_id == REG_QWORD:
        value = int(data) & 0xFFFFFFFFFFFFFFFF
        text = "0x%016X (%d)" % (value, value)
        result["display"] = result["full"] = text
    elif isinstance(data, (list, tuple)):
        items = [str(item) for item in data]
        result["display"] = _clip(" | ".join(items))
        result["full"] = "\n".join(items)
    elif isinstance(data, str):
        result["display"] = _clip(data)
        result["full"] = data
        if type_id == REG_EXPAND_SZ:
            import os
            result["expanded"] = os.path.expandvars(data)
    else:
        text = repr(data)
        result["display"] = _clip(text)
        result["full"] = text

    return result


def escape_reg_string(text: str) -> str:
    """转义 .reg 文件里的字符串值。"""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _encode_utf16(text: str) -> bytes:
    return text.encode("utf-16-le", errors="replace") + b"\x00\x00"


def _multi_sz_bytes(items: List[str]) -> bytes:
    payload = "".join(str(item) + "\x00" for item in items) + "\x00"
    return payload.encode("utf-16-le", errors="replace")


def _hex_block(prefix: str, raw: bytes, per_line: int = 24) -> List[str]:
    """生成 ``"name"=hex:...`` 的多行文本，超过一行用反斜杠续行。"""
    if not raw:
        return [prefix]
    lines: List[str] = []
    chunks = [raw[i:i + per_line] for i in range(0, len(raw), per_line)]
    for index, chunk in enumerate(chunks):
        body = ",".join("%02x" % byte for byte in chunk)
        if index < len(chunks) - 1:
            body += ","
        if index == 0:
            line = prefix + body
        else:
            line = "  " + body
        if index < len(chunks) - 1:
            line += "\\"
        lines.append(line)
    return lines


def reg_value_lines(name: str, type_id: int, data: Any) -> List[str]:
    """把单个值序列化成 .reg 文件中的若干行。"""
    key = "@" if not name else '"%s"' % escape_reg_string(name)
    prefix = key + "="

    if type_id == REG_SZ and isinstance(data, str):
        if any(char in data for char in "\r\n\x00"):
            return _hex_block(prefix + "hex(1):", _encode_utf16(data))
        return [prefix + '"%s"' % escape_reg_string(data)]

    if type_id == REG_EXPAND_SZ and isinstance(data, str):
        return _hex_block(prefix + "hex(2):", _encode_utf16(data))

    if type_id == REG_MULTI_SZ and isinstance(data, (list, tuple)):
        return _hex_block(prefix + "hex(7):", _multi_sz_bytes(list(data)))

    if type_id == REG_DWORD and isinstance(data, int):
        return [prefix + "dword:%08x" % (int(data) & 0xFFFFFFFF)]

    if type_id == REG_QWORD and isinstance(data, int):
        return _hex_block(prefix + "hex(b):", struct.pack("<Q", int(data) & 0xFFFFFFFFFFFFFFFF))

    if isinstance(data, (bytes, bytearray)):
        hex_prefix = prefix + ("hex:" if type_id == REG_BINARY else "hex(%x):" % type_id)
        return _hex_block(hex_prefix, bytes(data))

    if isinstance(data, str):
        return _hex_block(prefix + "hex(%x):" % type_id, _encode_utf16(data))

    if isinstance(data, (list, tuple)):
        return _hex_block(prefix + "hex(7):", _multi_sz_bytes([str(i) for i in data]))

    return [prefix + '"%s"' % escape_reg_string(str(data))]


def value_pair(described: Dict[str, Any]) -> Optional[str]:
    """详情面板里「类型 · 大小」这类小标签。"""
    if described.get("size") is None:
        return None
    return "%s · %d B" % (described["type"], described["size"])
