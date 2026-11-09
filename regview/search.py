"""注册表搜索：按子键名 / 值名 / 值数据匹配，带数量、时间与取消限制。"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Union

from .paths import leaf_name, normalize_path

CancelToken = Union[Callable[[], bool], Any, None]  # threading.Event 或可调用对象

VALID_SCOPES = ("both", "keys", "values")


def _cancelled(token: CancelToken) -> bool:
    if token is None:
        return False
    if callable(token):
        return bool(token())
    is_set = getattr(token, "is_set", None)
    return bool(is_set and is_set())


def search(
    registry,
    query: str,
    root: str,
    scope: str = "both",
    limit: int = 200,
    max_keys: int = 5000,
    time_limit: float = 6.0,
    cancel: CancelToken = None,
) -> Dict[str, Any]:
    """在 ``root`` 之下深度优先搜索，返回结构化结果。

    遍历对拒绝访问的键是容错的：记录 error 计数后继续其它分支。
    任一限制触发都会置 ``truncated``，前端据此提示用户缩小范围。
    """
    needle = (query or "").strip().lower()
    if not needle:
        raise ValueError("搜索关键字不能为空")
    if scope not in VALID_SCOPES:
        raise ValueError("未知搜索范围 %r" % scope)
    start = time.monotonic()
    root_path = normalize_path(root)
    results: List[Dict[str, Any]] = []
    scanned = 0
    errors = 0
    truncated: Optional[str] = None

    for item in registry.walk(root_path, max_keys=max_keys):
        scanned += 1
        if item.get("error"):
            errors += 1
        else:
            path = item["path"]
            if scope in ("both", "keys") and needle in leaf_name(path).lower():
                results.append({
                    "kind": "key", "path": path, "name": leaf_name(path),
                    "type": "", "detail": "子键",
                })
            if scope in ("both", "values"):
                for value in item.get("values", []):
                    if needle in str(value.get("name", "")).lower() or \
                       needle in str(value.get("display", "")).lower() or \
                       needle in str(value.get("full", "")).lower():
                        results.append({
                            "kind": "value", "path": path,
                            "name": value.get("name", "") or "(默认)",
                            "type": value.get("type", ""),
                            "detail": value.get("display", ""),
                        })

        if len(results) >= limit:
            truncated = "results"
            break
        if _cancelled(cancel):
            truncated = "cancelled"
            break
        if time.monotonic() - start >= time_limit:
            truncated = "time"
            break
    else:
        if scanned >= max_keys:
            truncated = "keys"

    return {
        "query": query,
        "scope": scope,
        "root": root_path,
        "results": results[:limit],
        "count": len(results[:limit]),
        "scanned": scanned,
        "errors": errors,
        "truncated": truncated,
        "elapsed": round(time.monotonic() - start, 3),
    }
