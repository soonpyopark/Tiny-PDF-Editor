"""Put bundled Qt6 bin on the Windows DLL search path before QtCore loads."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _meipass() -> Path | None:
    raw = getattr(sys, "_MEIPASS", None)
    return Path(raw) if raw else None


def _add_dir(path: Path) -> None:
    if not path.is_dir():
        return
    os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")
    adder = getattr(os, "add_dll_directory", None)
    if adder is not None:
        adder(str(path))


bundle = _meipass()
if bundle is not None:
    qt6 = bundle / "PyQt6" / "Qt6"
    _add_dir(qt6 / "bin")
    _add_dir(bundle)
    plugins = qt6 / "plugins"
    if plugins.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))
