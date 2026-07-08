"""Persisted list of recently opened PDF files with last-read page."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

MAX_RECENT_FILES = 10
_STORE_FILENAME = "recent_files.json"


def _store_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not base:
        base = str(Path.home() / ".tiny_pdf_editor")
    return Path(base) / _STORE_FILENAME


class RecentFilesStore:
    """Manages an ordered, de-duplicated list of recent PDF files.

    Each entry keeps the absolute path and the last page the user viewed so a
    file can be reopened at the same location. Newest entries come first and the
    list is capped at :data:`MAX_RECENT_FILES`.
    """

    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._path = _store_path()
        self.load()

    def load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            self._entries = []
            return
        entries: list[dict] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if not isinstance(path, str) or not path:
                    continue
                page = item.get("page", 0)
                page = page if isinstance(page, int) and page >= 0 else 0
                entries.append({"path": path, "page": page})
        self._entries = entries[:MAX_RECENT_FILES]

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    @staticmethod
    def _normalize(path: str) -> str:
        try:
            return str(Path(path).resolve())
        except OSError:
            return str(Path(path))

    def _index_of(self, path: str) -> int:
        target = self._normalize(path)
        for index, entry in enumerate(self._entries):
            if self._normalize(entry["path"]) == target:
                return index
        return -1

    def entries(self) -> list[dict]:
        return list(self._entries)

    def add(self, path: str, page: int = 0) -> None:
        """Move *path* to the front, preserving its stored page unless given."""
        normalized = self._normalize(path)
        existing_index = self._index_of(normalized)
        stored_page = page
        if existing_index >= 0:
            if page <= 0:
                stored_page = self._entries[existing_index].get("page", 0)
            self._entries.pop(existing_index)
        self._entries.insert(0, {"path": normalized, "page": max(0, stored_page)})
        del self._entries[MAX_RECENT_FILES:]
        self._save()

    def set_page(self, path: str, page: int) -> None:
        index = self._index_of(path)
        if index < 0:
            return
        self._entries[index]["page"] = max(0, int(page))
        self._save()

    def get_page(self, path: str) -> int:
        index = self._index_of(path)
        if index < 0:
            return 0
        return int(self._entries[index].get("page", 0))

    def remove(self, path: str) -> None:
        index = self._index_of(path)
        if index >= 0:
            self._entries.pop(index)
            self._save()

    def clear(self) -> None:
        self._entries = []
        self._save()

    def prune_missing(self) -> None:
        """Drop entries whose files no longer exist on disk."""
        kept = [e for e in self._entries if os.path.exists(e["path"])]
        if len(kept) != len(self._entries):
            self._entries = kept
            self._save()
