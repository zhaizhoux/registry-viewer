"""收藏夹：把常用注册表路径持久化到 ~/.regview/bookmarks.json。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .paths import leaf_name, normalize_path


def default_home() -> Path:
    override = os.environ.get("REGVIEW_HOME", "").strip()
    return Path(override) if override else Path.home() / ".regview"


class BookmarkStore:
    def __init__(self, home: Optional[Union[str, Path]] = None):
        self.home = Path(home) if home else default_home()
        self.file = self.home / "bookmarks.json"

    def _load(self) -> List[Dict[str, Any]]:
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict) and item.get("path")]

    def _save(self, items: List[Dict[str, Any]]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        temp = self.file.with_suffix(".json.tmp")
        temp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.file)

    def list(self) -> List[Dict[str, Any]]:
        return self._load()

    def add(self, path: str) -> List[Dict[str, Any]]:
        normalized = normalize_path(path)
        # 注册表键名大小写不敏感，去重时忽略大小写
        key = normalized.casefold()
        items = [item for item in self._load()
                 if str(item.get("path", "")).casefold() != key]
        items.insert(0, {
            "path": normalized,
            "name": leaf_name(normalized),
            "added_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        self._save(items)
        return items

    def remove(self, path: str) -> List[Dict[str, Any]]:
        normalized = normalize_path(path)
        key = normalized.casefold()
        items = [item for item in self._load()
                 if str(item.get("path", "")).casefold() != key]
        self._save(items)
        return items

    def clear(self) -> List[Dict[str, Any]]:
        self._save([])
        return []
