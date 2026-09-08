"""MyPortal-style startup splash screen."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QFontMetrics, QIcon, QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.resources import branding_path
from pdf_editor.version import (
    APP_BUILD_STAMP,
    APP_NAME,
    AUTHOR_LINK_TEXT,
    AUTHOR_URL,
    version_label,
)

SPLASH_BG = "#0a1a33"
SPLASH_MIN_WIDTH = 400
SPLASH_PAD_X = 36
SPLASH_PAD_Y = 30
SPLASH_CLUSTER_GAP = 16
SPLASH_MIN_MS = 700
_TITLE_STYLE = (
    "color: #ffffff; font-size: 22px; font-weight: 700; background: transparent;"
)
_LINK_STYLE = "color: #9aa8b8; font-size: 11px; background: transparent;"
_BUILD_STYLE = "color: #6e7b8c; font-size: 11px; background: transparent;"
_TITLE_TO_META = 8
_META_SPACING = 3

_about_splash: SplashScreen | None = None
_about_dismiss_filter: "_AboutDismissFilter | None" = None


class _AboutDismissFilter(QObject):
    """Close the about splash when the user clicks outside or on the splash itself."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        splash = _about_splash
        if splash is None or not splash.isVisible():
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        mouse = event
        if not isinstance(mouse, QMouseEvent):
            return False
        if mouse.button() != Qt.MouseButton.LeftButton:
            return False

        global_pos = mouse.globalPosition().toPoint()
        if not splash.frameGeometry().contains(global_pos):
            close_about_splash()
            return False

        link = splash._link_label
        if link is not None and link.isVisible():
            top_left = link.mapToGlobal(QPoint(0, 0))
            link_rect = QRect(top_left, link.size())
            if link_rect.contains(global_pos):
                return False

        close_about_splash()
        return False


def _install_about_dismiss_filter() -> None:
    global _about_dismiss_filter
    app = QApplication.instance()
    if app is None:
        return
    if _about_dismiss_filter is None:
        _about_dismiss_filter = _AboutDismissFilter()
    app.installEventFilter(_about_dismiss_filter)


def _remove_about_dismiss_filter() -> None:
    global _about_dismiss_filter
    app = QApplication.instance()
    if app is not None and _about_dismiss_filter is not None:
        app.removeEventFilter(_about_dismiss_filter)


def close_about_splash() -> None:
    global _about_splash
    if _about_splash is None:
        return
    splash = _about_splash
    _about_splash = None
    _remove_about_dismiss_filter()
    splash.close()


def _copy_column_metrics(
    title: QLabel, link: QLabel, build: QLabel | None
) -> tuple[int, int]:
    """Return (height, width) of the copy column, matching its layout spacing."""
    for widget in (title, link, build):
        if widget is not None:
            widget.ensurePolished()
    title_h = max(1, title.sizeHint().height())
    title_w = max(1, title.sizeHint().width())
    meta = [link]
    if build is not None:
        meta.append(build)
    meta_h = sum(max(1, row.sizeHint().height()) for row in meta)
    if len(meta) > 1:
        meta_h += _META_SPACING * (len(meta) - 1)
    meta_w = max(max(1, row.sizeHint().width()) for row in meta)
    height = title_h + _TITLE_TO_META + meta_h
    width = max(title_w, meta_w)
    if height <= 0:
        metrics = QFontMetrics(title.font())
        height = metrics.height() * (1 + len(meta)) + _TITLE_TO_META + _META_SPACING
    return max(1, height), max(1, width)


def _load_splash_logo(size: int) -> QPixmap:
    from PIL import Image as PilImage

    names = ("app_logo.png", "app_icon.png", "app_icon.ico")
    for name in names:
        path = branding_path(name)
        if not path.is_file():
            continue
        source = PilImage.open(path).convert("RGBA")
        box = source.getbbox()
        if box is not None:
            source = source.crop(box)
        source.thumbnail(
            (size, size),
            PilImage.Resampling.LANCZOS,
        )
        qimage = QImage(
            source.tobytes("raw", "RGBA"),
            source.width,
            source.height,
            source.width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        pixmap = QPixmap.fromImage(qimage)
        if not pixmap.isNull():
            return pixmap
    return QPixmap()


class SplashScreen(QWidget):
    """Frameless splash patterned after MyPortal."""

    def __init__(self, *, startup: bool = False) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        if startup:
            flags |= Qt.WindowType.SplashScreen
        super().__init__(None, flags)
        self._link_label: QLabel | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(f"background-color: {SPLASH_BG};")
        self._build_ui()

    def _build_ui(self) -> None:
        title = QLabel(f"{APP_NAME} {version_label()}")
        title.setStyleSheet(_TITLE_STYLE)
        title.setWordWrap(False)

        link = QLabel(
            f'<a href="{AUTHOR_URL}" style="color:#9aa8b8;text-decoration:none;">'
            f"{AUTHOR_LINK_TEXT}</a>"
        )
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setOpenExternalLinks(False)
        link.setStyleSheet(_LINK_STYLE)
        link.linkActivated.connect(lambda href: QDesktopServices.openUrl(QUrl(href)))
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._link_label = link

        build: QLabel | None = None
        if APP_BUILD_STAMP:
            build = QLabel(APP_BUILD_STAMP)
            build.setStyleSheet(_BUILD_STYLE)

        icon_size, copy_width = _copy_column_metrics(title, link, build)
        cluster_width = icon_size + SPLASH_CLUSTER_GAP + copy_width
        # Title is wider than the URL/stamp, so geometric center looks right-heavy.
        optical_left = min(8, max(0, (title.sizeHint().width() - link.sizeHint().width()) // 12))
        window_width = max(SPLASH_MIN_WIDTH, cluster_width + SPLASH_PAD_X * 2)
        self.setFixedSize(window_width, icon_size + SPLASH_PAD_Y * 2)

        for label in (title, link, build):
            if label is None:
                continue
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        cluster = QWidget()
        cluster.setStyleSheet("background: transparent;")
        cluster_row = QHBoxLayout(cluster)
        cluster_row.setContentsMargins(0, 0, 0, 0)
        cluster_row.setSpacing(SPLASH_CLUSTER_GAP)

        logo = _load_splash_logo(icon_size)
        if not logo.isNull():
            logo_label = QLabel()
            logo_label.setPixmap(logo)
            logo_label.setFixedSize(icon_size, icon_size)
            logo_label.setStyleSheet("background: transparent;")
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cluster_row.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignVCenter)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        content.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft)
        content.addSpacing(_TITLE_TO_META)
        meta = QVBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(_META_SPACING)
        meta.addWidget(link, 0, Qt.AlignmentFlag.AlignLeft)
        if build is not None:
            meta.addWidget(build, 0, Qt.AlignmentFlag.AlignLeft)
        content.addLayout(meta)
        cluster_row.addLayout(content)

        root = QHBoxLayout(self)
        root.setContentsMargins(
            SPLASH_PAD_X - optical_left,
            SPLASH_PAD_Y,
            SPLASH_PAD_X + optical_left,
            SPLASH_PAD_Y,
        )
        root.setSpacing(0)
        root.addWidget(cluster, 0, Qt.AlignmentFlag.AlignCenter)

    def show_centered(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - self.width()) // 2,
                geo.y() + (geo.height() - self.height()) // 2,
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
                close_about_splash()
                return
        except RuntimeError:
            _about_splash = None

    splash = SplashScreen(startup=False)
    _about_splash = splash
    splash.show_centered()
    _install_about_dismiss_filter()
    splash.destroyed.connect(_on_about_splash_destroyed)


def _on_about_splash_destroyed(_obj: QObject | None = None) -> None:
    global _about_splash
    _remove_about_dismiss_filter()
    _about_splash = None


def finish_loading_splash(splash: SplashScreen, elapsed_ms: int, on_done) -> None:
    """Close loading splash after minimum display time, then run *on_done*."""
    delay = max(0, SPLASH_MIN_MS - elapsed_ms)
    QTimer.singleShot(
        delay,
        lambda s=splash, done=on_done: _close_loading_and_run(s, done),
    )


def _close_loading_and_run(splash: SplashScreen, on_done) -> None:
    if splash.isVisible():
        splash.close()
    on_done()
