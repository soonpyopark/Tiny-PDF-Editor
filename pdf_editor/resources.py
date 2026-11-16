"""Resolve bundled asset paths in development and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def branding_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pdf_editor" / "branding" / name
    return _PACKAGE_DIR / "branding" / name


def _installed_branding_icon(name: str) -> Path | None:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for candidate in (
            exe_dir / name,
            exe_dir / "_internal" / "pdf_editor" / "branding" / name,
        ):
            if candidate.is_file():
                return candidate.resolve()
    icon_path = branding_path(name)
    if icon_path.is_file():
        return icon_path.resolve()
    return None


def installed_pdf_file_icon_path() -> Path | None:
    """Stable on-disk path for Windows shell PDF file icons."""
    return _installed_branding_icon("pdf_file_icon.ico")


def installed_app_icon_path() -> Path | None:
    """Stable on-disk path for the Windows app / shortcut icon."""
    return _installed_branding_icon("app_icon.ico")
