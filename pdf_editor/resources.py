"""Resolve bundled asset paths in development and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QWidget

_PACKAGE_DIR = Path(__file__).resolve().parent
_WINDOWS_APP_ID = "TinyPDFEditor.TinyPDFEditor.1"


def branding_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pdf_editor" / "branding" / name
    return _PACKAGE_DIR / "branding" / name


def installed_pdf_file_icon_path() -> Path | None:
    """Stable on-disk path for Windows shell PDF file icons."""
    name = "pdf_file_icon.ico"
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


def init_platform() -> None:
    """Run before QApplication so Windows uses the app icon on the taskbar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass


def apply_macos_app_style(app) -> None:
    """Keep macOS UI on a stable light Fusion look (no-op on other platforms)."""
    if sys.platform != "darwin":
        return

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QApplication

    if not isinstance(app, QApplication):
        return

    app.setStyle("Fusion")
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except (AttributeError, TypeError):
        pass

    palette = QPalette()
    window = QColor("#eeeeee")
    base = QColor("#ffffff")
    text = QColor("#222222")
    disabled = QColor("#888888")
    highlight = QColor("#1a73e8")
    highlighted_text = QColor("#ffffff")
    button = QColor("#f5f5f5")

    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f5f5f5"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, button)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.ToolTipBase, base)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, highlighted_text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#888888"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled
    )
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled
    )
    app.setPalette(palette)


def load_app_icon() -> QIcon:
    candidates = (
        "app_icon.icns",
        "app_icon.png",
        "app_icon.ico",
        "app_logo.png",
    )
    for name in candidates:
        icon_path = branding_path(name)
        if not icon_path.is_file():
            continue
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    return QIcon()


def apply_windows_window_icon(widget: QWidget) -> None:
    """Set the native taskbar icon for frameless windows on Windows."""
    if sys.platform != "win32":
        return

    icon_path = branding_path("app_icon.ico")
    if not icon_path.is_file():
        return

    hwnd = int(widget.winId())
    if not hwnd:
        return

    try:
        import ctypes

        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x10
        LR_DEFAULTSIZE = 0x40

        path = str(icon_path.resolve())
        for icon_size, icon_type in ((0, ICON_BIG), (16, ICON_SMALL)):
            hicon = user32.LoadImageW(
                None,
                path,
                IMAGE_ICON,
                icon_size,
                icon_size,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if hicon:
                user32.SendMessageW(hwnd, WM_SETICON, icon_type, hicon)
    except (AttributeError, OSError):
        pass
