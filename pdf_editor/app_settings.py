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
        self.hwp_save_folder: str = default_downloads_folder()
        self.hwp_save_beside_source: bool = True
        self.ocr_folder: str = ""
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
        hwp_folder = data.get("hwp_save_folder")
        if isinstance(hwp_folder, str) and hwp_folder.strip():
            candidate = Path(hwp_folder)
            if candidate.is_dir():
                self.hwp_save_folder = str(candidate)
            else:
                self.hwp_save_folder = default_downloads_folder()
        beside = data.get("hwp_save_beside_source")
        if isinstance(beside, bool):
            self.hwp_save_beside_source = beside
        ocr_folder = data.get("ocr_folder")
        if isinstance(ocr_folder, str) and ocr_folder.strip():
            candidate = Path(ocr_folder)
            if candidate.is_dir():
                self.ocr_folder = str(candidate)
            else:
                self.ocr_folder = ""
        else:
            self.ocr_folder = ""

    def save(self) -> None:
        payload = {
            "merge_save_folder": self.merge_save_folder,
            "hwp_save_folder": self.hwp_save_folder,
            "hwp_save_beside_source": self.hwp_save_beside_source,
            "ocr_folder": self.ocr_folder,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
