"""Windows frozen-app DLL search path for PyQt6 / Qt6Core."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Python 3.8+ removes a directory from the DLL search path when the object
# returned by os.add_dll_directory is garbage-collected. Keep handles alive
# for the whole process so Qt6Core/ICU can still be found after import.
_DLL_DIRECTORY_HANDLES: list[object] = []
_PRELOADED_DLLS: list[object] = []

_PRELOAD_DLL_NAMES = (
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "concrt140.dll",
    "icu.dll",
    "icuuc.dll",
    "icuin.dll",
    "Qt6Core.dll",
)


def _add_dir(path: Path) -> None:
    if not path.is_dir():
        return
    os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")
    adder = getattr(os, "add_dll_directory", None)
    if adder is None:
        return
    try:
        _DLL_DIRECTORY_HANDLES.append(adder(str(path)))
    except (OSError, FileExistsError, ValueError):
        pass


def _file_in_dir(folder: Path, name: str) -> Path | None:
    direct = folder / name
    if direct.is_file():
        return direct
    target = name.lower()
    try:
        for entry in folder.iterdir():
            if entry.is_file() and entry.name.lower() == target:
                return entry
    except OSError:
        return None
    return None


def _preload_runtime_dlls(folders: list[Path]) -> None:
    """Load VC / ICU / Qt6Core from known bundle dirs before import QtCore."""
    if sys.platform != "win32":
        return
    import ctypes

    loaded: set[str] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        for name in _PRELOAD_DLL_NAMES:
            key = name.lower()
            if key in loaded:
                continue
            candidate = _file_in_dir(folder, name)
            if candidate is None:
                continue
            try:
                _PRELOADED_DLLS.append(ctypes.WinDLL(str(candidate)))
                loaded.add(key)
            except OSError:
                continue
    _preload_python_dlls(folders)


def _preload_python_dlls(folders: list[Path]) -> None:
    """QtCore.pyd imports python3.dll. Load the bundled copies by full path."""
    import ctypes

    loaded: set[str] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name.lower()
            if not entry.is_file() or not name.startswith("python3") or not name.endswith(".dll"):
                continue
            if name in loaded:
                continue
            try:
                _PRELOADED_DLLS.append(ctypes.WinDLL(str(entry)))
                loaded.add(name)
            except OSError:
                continue


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
    folders = [
        exe_dir,
        bundle,
        pyqt,
        qt6 / "bin",
        plugins,
        plugins / "platforms",
    ]

    for folder in folders:
        _add_dir(folder)

    if plugins.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))

    _preload_runtime_dlls(folders)
