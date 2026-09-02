"""Windows frozen-app DLL search path for PyQt6 / Qt6Core."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _add_dir(path: Path) -> None:
    if not path.is_dir():
        return
    os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")
    adder = getattr(os, "add_dll_directory", None)
    if adder is None:
        return
    try:
        adder(str(path))
    except (OSError, FileExistsError, ValueError):
        pass


def prepare_qt_dll_paths() -> None:
    """Put Qt and VC runtime folders on the DLL search path before QtCore loads."""
    if not getattr(sys, "frozen", False):
        return

    exe_dir = Path(sys.executable).resolve().parent
    meipass = getattr(sys, "_MEIPASS", None)
    bundle = Path(meipass) if meipass else exe_dir / "_internal"
    pyqt = bundle / "PyQt6"
    qt6 = pyqt / "Qt6"
    plugins = qt6 / "plugins"

    for folder in (
        exe_dir,
        bundle,
        pyqt,
        qt6 / "bin",
        plugins,
        plugins / "platforms",
    ):
        _add_dir(folder)

    if plugins.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))
