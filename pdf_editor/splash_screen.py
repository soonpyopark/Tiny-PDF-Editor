"""MyPortal-style startup splash screen."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pdf_editor.resources import branding_path

SPLASH_BG = "#0a1a33"
SPLASH_WIDTH = 400
SPLASH_HEIGHT = 129
SPLASH_MIN_MS = 700
AUTHOR_NAME = "청년안민규"
AUTHOR_URL = "https://note4all.tistory.com"
APP_SPLASH_TITLE = "Tiny PDF Editor"

_about_splash: SplashScreen | None = None


def _load_splash_logo() -> QPixmap:
    for name in ("app_logo.png", "app_icon.png", "app_icon.ico"):
        path = branding_path(name)
        if path.is_file():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap.scaled(
                    68,
                    68,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
    return QPixmap()


class SplashScreen(QWidget):
    """Frameless splash patterned after MyPortal."""

    def __init__(self, *, startup: bool = False) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        if startup:
            flags |= Qt.WindowType.SplashScreen
        super().__init__(None, flags)
        self._link_label: QLabel | None = None
        self.setFixedSize(SPLASH_WIDTH, SPLASH_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(f"background-color: {SPLASH_BG};")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(18)
        root.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        logo = _load_splash_logo()
        if not logo.isNull():
            logo_label = QLabel()
            logo_label.setPixmap(logo)
            logo_label.setFixedSize(68, 68)
            logo_label.setStyleSheet("background: transparent;")
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignVCenter)

        content = QVBoxLayout()
        content.setSpacing(5)
        content.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title = QLabel(APP_SPLASH_TITLE)
        title.setStyleSheet(
            "color: #ffffff; font-size: 22px; font-weight: 700; background: transparent;"
        )
        title.setWordWrap(True)
        content.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)

        credit = QLabel(f'Made by <span style="color:#f4c430;font-weight:700;">{AUTHOR_NAME}</span>')
        credit.setTextFormat(Qt.TextFormat.RichText)
        credit.setStyleSheet("color: #ffffff; font-size: 14px; background: transparent;")
        content.addWidget(credit, 0, Qt.AlignmentFlag.AlignVCenter)

        link = QLabel(
            f'<a href="{AUTHOR_URL}" style="color:#a8b4c4;text-decoration:none;">{AUTHOR_URL}</a>'
        )
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setOpenExternalLinks(False)
        link.setStyleSheet("font-size: 11px; background: transparent;")
        link.linkActivated.connect(lambda href: QDesktopServices.openUrl(QUrl(href)))
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        content.addWidget(link, 0, Qt.AlignmentFlag.AlignVCenter)
        self._link_label = link

        root.addLayout(content, 1)

    def show_centered(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - SPLASH_WIDTH) // 2,
                geo.y() + (geo.height() - SPLASH_HEIGHT) // 2,
            )
        self.show()
        self.raise_()
        self.activateWindow()


def show_loading_splash(app_icon: QIcon | None = None) -> SplashScreen:
    splash = SplashScreen(startup=True)
    if app_icon is not None and not app_icon.isNull():
        splash.setWindowIcon(app_icon)
    splash.show_centered()
    QApplication.processEvents()
    return splash


def toggle_about_splash() -> None:
    """Show or hide the about splash from the menu."""
    global _about_splash
    if _about_splash is not None:
        try:
            if _about_splash.isVisible():
                splash = _about_splash
                _about_splash = None
                splash.close()
                return
        except RuntimeError:
            _about_splash = None

    splash = SplashScreen(startup=False)
    _about_splash = splash
    splash.show_centered()
    splash.destroyed.connect(lambda *_: _on_about_splash_destroyed(splash))


def _on_about_splash_destroyed(splash: SplashScreen) -> None:
    global _about_splash
    if _about_splash is splash:
        _about_splash = None


def finish_loading_splash(splash: SplashScreen, elapsed_ms: int, on_done) -> None:
    """Close loading splash after minimum display time, then run *on_done*."""
    delay = max(0, SPLASH_MIN_MS - elapsed_ms)
    QTimer.singleShot(delay, lambda: _close_loading_and_run(splash, on_done))


def _close_loading_and_run(splash: SplashScreen, on_done) -> None:
    if splash.isVisible():
        splash.close()
    on_done()
