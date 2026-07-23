"""In-app print dialog with lazy single-page preview (safe for large PDFs)."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from collections.abc import Iterator
from enum import Enum

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QResizeEvent, QShowEvent
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.document import PdfDocument
from pdf_editor.print_utils import print_document, render_preview_page

_UNIFIED_PRINT_KEY = r"Software\Microsoft\Print\UnifiedPrintDialog"
_PREFER_LEGACY_VALUE = "PreferLegacyPrintDialog"
_CACHE_RADIUS = 1
_FIT_BTN_SIZE = (36, 24)


class _PreviewFit(Enum):
    WIDTH = "width"
    HEIGHT = "height"
    PAGE = "page"


@contextmanager
def prefer_legacy_windows_print_dialog() -> Iterator[None]:
    """Avoid the Windows unified dialog empty-preview message when possible."""
    if sys.platform != "win32":
        yield
        return

    import winreg

    previous: int | None = None
    existed = False
    key = None
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            _UNIFIED_PRINT_KEY,
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        )
        try:
            value, _reg_type = winreg.QueryValueEx(key, _PREFER_LEGACY_VALUE)
            previous = int(value)
            existed = True
        except OSError:
            previous = None
            existed = False
        winreg.SetValueEx(key, _PREFER_LEGACY_VALUE, 0, winreg.REG_DWORD, 1)
        yield
    except OSError:
        yield
    finally:
        if key is not None:
            try:
                if existed and previous is not None:
                    winreg.SetValueEx(
                        key,
                        _PREFER_LEGACY_VALUE,
                        0,
                        winreg.REG_DWORD,
                        previous,
                    )
                elif not existed:
                    try:
                        winreg.DeleteValue(key, _PREFER_LEGACY_VALUE)
                    except OSError:
                        pass
            finally:
                winreg.CloseKey(key)


class DocumentPrintDialog(QDialog):
    """Print UI that previews one page at a time (does not rasterize the whole PDF)."""

    def __init__(
        self,
        document: PdfDocument,
        parent: QWidget | None = None,
        *,
        title: str = "인쇄",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 720)
        self._document = document
        self._page_index = 0
        self._cache: dict[int, QPixmap] = {}
        self._source_pixmap = QPixmap()
        self._fit_mode = _PreviewFit.HEIGHT
        self._printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        self._printer.setDocName(document.display_name)
        if document.page_count > 0:
            self._printer.setFromTo(1, document.page_count)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hint = QLabel(
            "미리보기는 현재 페이지만 표시합니다. 페이지가 많은 문서도 안전하게 열립니다."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        nav = QHBoxLayout()
        nav.setSpacing(6)

        self._btn_prev = QToolButton()
        self._btn_prev.setText("◀")
        self._btn_prev.setToolTip("이전 페이지")
        self._btn_prev.clicked.connect(self._go_prev)
        nav.addWidget(self._btn_prev)

        self._page_label = QLabel()
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setMinimumWidth(120)
        nav.addWidget(self._page_label)

        self._btn_next = QToolButton()
        self._btn_next.setText("▶")
        self._btn_next.setToolTip("다음 페이지")
        self._btn_next.clicked.connect(self._go_next)
        nav.addWidget(self._btn_next)

        nav.addSpacing(8)

        self._btn_fit_width = QPushButton("너비")
        self._btn_fit_width.setFixedSize(*_FIT_BTN_SIZE)
        self._btn_fit_width.setToolTip("너비 맞추기")
        self._btn_fit_width.clicked.connect(lambda: self._set_fit_mode(_PreviewFit.WIDTH))
        nav.addWidget(self._btn_fit_width)

        self._btn_fit_height = QPushButton("높이")
        self._btn_fit_height.setFixedSize(*_FIT_BTN_SIZE)
        self._btn_fit_height.setToolTip("높이 맞추기")
        self._btn_fit_height.clicked.connect(lambda: self._set_fit_mode(_PreviewFit.HEIGHT))
        nav.addWidget(self._btn_fit_height)

        self._btn_fit_page = QPushButton("맞춤")
        self._btn_fit_page.setFixedSize(*_FIT_BTN_SIZE)
        self._btn_fit_page.setToolTip("페이지 맞추기")
        self._btn_fit_page.clicked.connect(lambda: self._set_fit_mode(_PreviewFit.PAGE))
        nav.addWidget(self._btn_fit_page)

        nav.addStretch(1)

        self._btn_setup = QPushButton("프린터 설정...")
        self._btn_setup.clicked.connect(self._configure_printer)
        nav.addWidget(self._btn_setup)
        root.addLayout(nav)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet("QScrollArea { background-color: #efefef; border: none; }")
        self._scroll.viewport().setStyleSheet("background-color: #efefef;")
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self._preview_label.setStyleSheet("background-color: #efefef;")
        self._scroll.setWidget(self._preview_label)
        root.addWidget(self._scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        print_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        print_btn.setText("인쇄")
        print_btn.setDefault(True)
        buttons.accepted.connect(self._print)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._refresh_preview()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Layout/viewport size is reliable only after the dialog is shown.
        QTimer.singleShot(0, self._apply_fit)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_fit()

    def _page_count(self) -> int:
        return self._document.page_count

    def _go_prev(self) -> None:
        if self._page_index <= 0:
            return
        self._page_index -= 1
        self._refresh_preview()

    def _go_next(self) -> None:
        if self._page_index >= self._page_count() - 1:
            return
        self._page_index += 1
        self._refresh_preview()

    def _set_fit_mode(self, mode: _PreviewFit) -> None:
        self._fit_mode = mode
        self._apply_fit()

    def _pixmap_for(self, page_index: int) -> QPixmap:
        cached = self._cache.get(page_index)
        if cached is not None and not cached.isNull():
            return cached
        pixmap = render_preview_page(self._document, page_index)
        self._cache[page_index] = pixmap
        keep = {
            index
            for index in range(
                max(0, self._page_index - _CACHE_RADIUS),
                min(self._page_count(), self._page_index + _CACHE_RADIUS + 1),
            )
        }
        for key in list(self._cache):
            if key not in keep and key != page_index:
                del self._cache[key]
        return pixmap

    def _apply_fit(self) -> None:
        if self._source_pixmap.isNull():
            return
        viewport = self._scroll.viewport().size()
        # Avoid locking in a tiny scale before the layout finishes.
        if viewport.width() < 80 or viewport.height() < 80:
            return
        view_w = max(1, viewport.width() - 4)
        view_h = max(1, viewport.height() - 4)
        src_w = max(1, self._source_pixmap.width())
        src_h = max(1, self._source_pixmap.height())

        if self._fit_mode is _PreviewFit.WIDTH:
            scale = view_w / src_w
        elif self._fit_mode is _PreviewFit.HEIGHT:
            scale = view_h / src_h
        else:
            scale = min(view_w / src_w, view_h / src_h)

        target_w = max(1, int(src_w * scale))
        target_h = max(1, int(src_h * scale))
        scaled = self._source_pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)
        self._preview_label.resize(scaled.size())
    def _refresh_preview(self) -> None:
        count = self._page_count()
        if count <= 0:
            self._source_pixmap = QPixmap()
            self._preview_label.clear()
            self._preview_label.setText("인쇄할 페이지가 없습니다.")
            self._page_label.setText("0 / 0")
            self._btn_prev.setEnabled(False)
            self._btn_next.setEnabled(False)
            return

        self._page_index = max(0, min(self._page_index, count - 1))
        self._page_label.setText(f"{self._page_index + 1} / {count}")
        self._btn_prev.setEnabled(self._page_index > 0)
        self._btn_next.setEnabled(self._page_index < count - 1)

        pixmap = self._pixmap_for(self._page_index)
        if pixmap.isNull():
            self._source_pixmap = QPixmap()
            self._preview_label.clear()
            self._preview_label.setText("미리보기를 만들 수 없습니다.")
            return

        self._source_pixmap = pixmap
        self._apply_fit()

    def _configure_printer(self) -> None:
        with prefer_legacy_windows_print_dialog():
            dialog = QPrintDialog(self._printer, self)
            dialog.exec()

    def _print(self) -> None:
        with prefer_legacy_windows_print_dialog():
            dialog = QPrintDialog(self._printer, self)
            if dialog.exec() != QPrintDialog.DialogCode.Accepted:
                return

        total_guess = self._page_count()
        progress = QProgressDialog("인쇄 중…", "취소", 0, max(1, total_guess), self)
        progress.setWindowTitle("인쇄")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(400)
        progress.setValue(0)
        cancelled = {"value": False}

        def on_progress(current: int, total: int) -> bool:
            progress.setMaximum(max(1, total))
            progress.setValue(current)
            progress.setLabelText(f"인쇄 중… ({current} / {total})")
            if progress.wasCanceled():
                cancelled["value"] = True
                return False
            return True

        try:
            print_document(self._document, self._printer, progress=on_progress)
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "인쇄 오류", str(exc))
            return

        progress.close()
        if cancelled["value"]:
            QMessageBox.information(self, "인쇄", "인쇄가 취소되었습니다.")
            return
        self.accept()
