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
        self.virtual_printer_enabled: bool | None = None
        self.page_nav_side: str = "hidden"
        self.page_nav_chosen: bool = False
        self.open_in_new_window: bool = True
        self.skipped_update_platform: str = ""
        self.skipped_update_version: str = ""
        self.skipped_update_stamp: str = ""
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
        printer = data.get("virtual_printer_enabled")
        if isinstance(printer, bool):
            self.virtual_printer_enabled = printer
        # Only restore overlay placement after the user has toggled it.
        # Older builds wrote the previous default ("right") on every quit.
        if data.get("page_nav_chosen") is True:
            nav_side = data.get("page_nav_side")
            if nav_side in ("left", "right", "hidden"):
                self.page_nav_side = nav_side
                self.page_nav_chosen = True
        open_new = data.get("open_in_new_window")
        if isinstance(open_new, bool):
            self.open_in_new_window = open_new
        platform = data.get("skipped_update_platform")
        version = data.get("skipped_update_version")
        stamp = data.get("skipped_update_stamp")
        if (
            isinstance(platform, str)
            and isinstance(version, str)
            and isinstance(stamp, str)
        ):
            self.skipped_update_platform = platform.strip()
            self.skipped_update_version = version.strip()
            self.skipped_update_stamp = stamp.strip()

    def skipped_update_key(self) -> tuple[str, str, str]:
        return (
            self.skipped_update_platform,
            self.skipped_update_version,
            self.skipped_update_stamp,
        )

    def set_skipped_update(self, platform: str, version: str, stamp: str) -> None:
        self.skipped_update_platform = platform.strip()
        self.skipped_update_version = version.strip()
        self.skipped_update_stamp = stamp.strip()

    def save(self) -> None:
        payload = {
            "merge_save_folder": self.merge_save_folder,
            "hwp_save_folder": self.hwp_save_folder,
            "hwp_save_beside_source": self.hwp_save_beside_source,
            "virtual_printer_enabled": self.virtual_printer_enabled,
            "page_nav_side": (
                self.page_nav_side if self.page_nav_chosen else "hidden"
            ),
            "page_nav_chosen": self.page_nav_chosen,
            "open_in_new_window": self.open_in_new_window,
            "skipped_update_platform": self.skipped_update_platform,
            "skipped_update_version": self.skipped_update_version,
            "skipped_update_stamp": self.skipped_update_stamp,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
