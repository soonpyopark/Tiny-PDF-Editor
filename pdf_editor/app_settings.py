"""Persisted application settings (AppData JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

_STORE_FILENAME = "app_settings.json"


def _store_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not base:
        base = str(Path.home() / ".tiny_pdf_editor")
    return Path(base) / _STORE_FILENAME


def default_downloads_folder() -> str:
    path = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DownloadLocation
    )
    if path:
        return str(Path(path))
    return str(Path.home() / "Downloads")


class AppSettings:
    """Small key/value settings store loaded once and saved on demand."""

    def __init__(self) -> None:
        self._path = _store_path()
        self.merge_save_folder: str = default_downloads_folder()
        self.load()

    def load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        folder = data.get("merge_save_folder")
        if isinstance(folder, str) and folder.strip():
            candidate = Path(folder)
            if candidate.is_dir():
                self.merge_save_folder = str(candidate)
            else:
                self.merge_save_folder = default_downloads_folder()

    def save(self) -> None:
        payload = {
            "merge_save_folder": self.merge_save_folder,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
