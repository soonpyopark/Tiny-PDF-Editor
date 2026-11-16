"""Small shared path helpers (the app's own settings live in the Neo app, not here)."""

from __future__ import annotations

from pathlib import Path


def default_downloads_folder() -> str:
    return str(Path.home() / "Downloads")
