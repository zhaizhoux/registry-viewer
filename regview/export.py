"""把某个键及其子键导出成 .reg / JSON / CSV。"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Any, Dict, Tuple

from .paths import leaf_name, normalize_path
from .values import reg_value_lines

FORMATS = ("reg", "json", "csv")
REG_HEADER = "Windows Registry Editor Version 5.00"


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")
    return cleaned[:48] or "registry"


def _export_reg(registry, path: str, max_keys: int) -> Tuple[str, Dict[str, Any]]:
    lines = [REG_HEADER, ""]
    stats = {"keys": 0, "values": 0, "errors": 0, "truncated": False}
    count = 0
    for item in registry.walk(path, max_keys=max_keys):
        count += 1
        if item.get("error"):
            stats["errors"] += 1
            lines.append("; 跳过 %s：%s" % (item["path"], item["error"]["message"]))
            lines.append("")
            continue
        stats["keys"] += 1
        lines.append("[%s]" % item["path"])
        for name, type_id, data in item.get("raw_values", []):
            lines.extend(reg_value_lines(name, type_id, data))
            stats["values"] += 1
        lines.append("")
    stats["truncated"] = count >= max_keys
    return "\r\n".join(lines), stats


def _export_json(registry, path: str, max_keys: int) -> Tuple[str, Dict[str, Any]]:
    keys = []
    stats = {"keys": 0, "values": 0, "errors": 0, "truncated": False}
    count = 0
    for item in registry.walk(path, max_keys=max_keys):
        count += 1
        if item.get("error"):
            stats["errors"] += 1
            keys.append({"path": item["path"], "error": item["error"]["message"]})
            continue
        values = [
            {
                "name": value["name"],
                "type": value["type"],
                "type_id": value["type_id"],
                "size": value["size"],
                "data": value["full"],
            }
            for value in item.get("values", [])
        ]
        stats["keys"] += 1
        stats["values"] += len(values)
        keys.append({"path": item["path"], "subkeys": item.get("subkeys", []), "values": values})
    stats["truncated"] = count >= max_keys
    payload = {
        "tool": "regview",
        "readonly": True,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": path,
        "truncated": stats["truncated"],
        "keys": keys,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2), stats


def _export_csv(registry, path: str, max_keys: int) -> Tuple[str, Dict[str, Any]]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["key_path", "value_name", "type", "data", "size_bytes"])
    stats = {"keys": 0, "values": 0, "errors": 0, "truncated": False}
    count = 0
    for item in registry.walk(path, max_keys=max_keys):
        count += 1
        if item.get("error"):
            stats["errors"] += 1
            continue
        stats["keys"] += 1
        for value in item.get("values", []):
            data = str(value.get("full", "")).replace("\r", "\\r").replace("\n", "\\n")
            writer.writerow([item["path"], value["name"] or "(默认)",
                             value["type"], data, value["size"]])
            stats["values"] += 1
    stats["truncated"] = count >= max_keys
    return buffer.getvalue(), stats


def build_export(registry, path: str, fmt: str = "reg", max_keys: int = 2000) -> Dict[str, Any]:
    """返回可直接写入磁盘/HTTP 响应的导出结果。"""
    if fmt not in FORMATS:
        raise ValueError("未知导出格式 %r，可用：%s" % (fmt, ", ".join(FORMATS)))
    root = normalize_path(path)
    if fmt == "reg":
        text, stats = _export_reg(registry, root, max_keys)
        encoding = "utf-16"  # regedit 5.00 文件原生格式，Python 会写 BOM
        content_type = "text/plain; charset=utf-16"
    elif fmt == "json":
        text, stats = _export_json(registry, root, max_keys)
        encoding = "utf-8"
        content_type = "application/json; charset=utf-8"
    else:
        text, stats = _export_csv(registry, root, max_keys)
        encoding = "utf-8-sig"  # Excel 打开中文不乱码
        content_type = "text/csv; charset=utf-8"

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = "regview-%s-%s.%s" % (_safe_filename(leaf_name(root)), stamp, fmt)
    return {
        "text": text,
        "encoding": encoding,
        "content_type": content_type,
        "filename": filename,
        "stats": stats,
    }
