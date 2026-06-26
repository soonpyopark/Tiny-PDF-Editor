"""Application main window."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from enum import Enum
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QShortcut, QShowEvent
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from pdf_editor.document import PdfDocument, SearchHit, format_file_size
from pdf_editor.page_viewer import PageViewer
from pdf_editor.reduce_size_dialog import ReduceSizeDialog
from pdf_editor.resources import (
  apply_windows_window_icon,
  init_platform,
  load_app_icon,
)
from pdf_editor.splash_screen import finish_loading_splash, show_loading_splash, toggle_about_splash
from pdf_editor.thumbnail_panel import (
  DEFAULT_THUMB_SCALE_LEVEL,
  THUMB_SCALE_LEVELS,
  ThumbnailPanel,
  thumb_scale_for_level,
)


AUTHOR_URL = "https://note4all.tistory.com"
APP_TITLE = "Tiny PDF Editor"
APP_BORDER_COLOR = "#333333"
APP_WINDOW_BACKGROUND = "#eeeeee"
APP_BORDER_WIDTH = 1
DEFAULT_WINDOW_WIDTH = 1024
DEFAULT_WINDOW_HEIGHT = 900
MIN_WINDOW_WIDTH = 520
MIN_WINDOW_HEIGHT = 480


class CloseSaveChoice(Enum):
    SAVE_AS = "save_as"
    DISCARD = "discard"
    CANCEL = "cancel"


def _ask_save_modified(parent: QWidget, title: str, text: str) -> CloseSaveChoice:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)

    layout = QVBoxLayout(dialog)
    message = QLabel(text)
    message.setWordWrap(True)
    layout.addWidget(message)

    button_row = QHBoxLayout()
    button_row.addStretch(1)

    save_button = QPushButton("다른이름으로 저장하고 닫기")
    discard_button = QPushButton("저장하지 않고 닫기")
    cancel_button = QPushButton("취소")
    result = CloseSaveChoice.CANCEL

    def choose_save() -> None:
        nonlocal result
        result = CloseSaveChoice.SAVE_AS
        dialog.accept()

    def choose_discard() -> None:
        nonlocal result
        result = CloseSaveChoice.DISCARD
        dialog.accept()

    save_button.clicked.connect(choose_save)
    discard_button.clicked.connect(choose_discard)
    cancel_button.clicked.connect(dialog.reject)

    button_row.addWidget(save_button)
    button_row.addWidget(discard_button)
    button_row.addWidget(cancel_button)
    layout.addLayout(button_row)

    save_button.setDefault(True)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        return result
    return CloseSaveChoice.CANCEL


class TabSearchBar(QWidget):
  """Search controls aligned with the document tab row."""

  search_requested = pyqtSignal(str)
  search_next = pyqtSignal()
  search_prev = pyqtSignal()

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("tabSearchBar")

    layout = QHBoxLayout(self)
    self._layout = layout
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    self.search_edit = QLineEdit()
    self.search_edit.setPlaceholderText("텍스트 검색")
    self.search_edit.setClearButtonEnabled(True)
    self.search_edit.setFixedSize(148, 24)
    self.search_edit.returnPressed.connect(self._emit_search)
    self.search_edit.textChanged.connect(self._on_search_text_changed)
    layout.addWidget(self.search_edit)

    self.btn_search_prev = QPushButton("◀")
    self.btn_search_prev.setFixedSize(24, 24)
    self.btn_search_prev.setToolTip("이전 결과")
    self.btn_search_prev.clicked.connect(self.search_prev.emit)
    layout.addWidget(self.btn_search_prev)

    self.btn_search_next = QPushButton("▶")
    self.btn_search_next.setFixedSize(24, 24)
    self.btn_search_next.setToolTip("다음 결과")
    self.btn_search_next.clicked.connect(self.search_next.emit)
    layout.addWidget(self.btn_search_next)

    self.search_status = QLabel("[ 0 / 0 ]")
    self.search_status.setFixedWidth(72)
    self.search_status.setAlignment(
      Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    layout.addWidget(self.search_status)

  def focus_search(self) -> None:
    self.search_edit.setFocus()
    self.search_edit.selectAll()

  def search_query(self) -> str:
    return self.search_edit.text().strip()

  def set_search_status(self, current: int, total: int) -> None:
    self.search_status.setText(f"[ {current} / {total} ]")

  def set_right_inset(self, pixels: int) -> None:
    self._layout.setContentsMargins(0, 0, max(0, pixels), 0)
    self.updateGeometry()

  def _emit_search(self) -> None:
    self.search_requested.emit(self.search_edit.text().strip())

  def _on_search_text_changed(self, text: str) -> None:
    if not text.strip():
      self.search_requested.emit("")


class TitleBar(QWidget):
  """Title row: icon, app name, attribution link, and window controls."""

  def __init__(self, window: QMainWindow) -> None:
    super().__init__(window)
    self._window = window
    self._drag_offset: QPoint | None = None
    self.setObjectName("appTitleBar")
    self.setFixedHeight(32)

    layout = QHBoxLayout(self)
    layout.setContentsMargins(8, 0, 0, 0)
    layout.setSpacing(8)

    icon_label = QLabel()
    icon_label.setFixedSize(16, 16)
    icon = window.windowIcon()
    if not icon.isNull():
      icon_label.setPixmap(icon.pixmap(16, 16))
    layout.addWidget(icon_label)

    title = QLabel(APP_TITLE)
    layout.addWidget(title)

    credit = QLabel(
      f'- Made by : 청년안민규 (<a href="{AUTHOR_URL}">{AUTHOR_URL}</a>)'
    )
    credit.setTextFormat(Qt.TextFormat.RichText)
    credit.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    credit.setOpenExternalLinks(False)
    credit.linkActivated.connect(
      lambda href: QDesktopServices.openUrl(QUrl(href))
    )
    layout.addWidget(credit)

    layout.addStretch(1)

    style = window.style()
    self.btn_close = QPushButton()
    for pixmap, handler, btn in (
      (QStyle.StandardPixmap.SP_TitleBarMinButton, window.showMinimized, QPushButton()),
      (QStyle.StandardPixmap.SP_TitleBarMaxButton, self._toggle_maximize, QPushButton()),
      (QStyle.StandardPixmap.SP_TitleBarCloseButton, window.close, self.btn_close),
    ):
      btn.setIcon(style.standardIcon(pixmap))
      btn.setFixedSize(46, 32)
      btn.setFlat(True)
      btn.clicked.connect(handler)
      layout.addWidget(btn)

  def _toggle_maximize(self) -> None:
    if self._window.isMaximized():
      self._window.showNormal()
    else:
      self._window.showMaximized()

  def mousePressEvent(self, event) -> None:
    if event.button() == Qt.MouseButton.LeftButton:
      self._drag_offset = (
        event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
      )
    super().mousePressEvent(event)

  def mouseMoveEvent(self, event) -> None:
    if (
      self._drag_offset is not None
      and event.buttons() & Qt.MouseButton.LeftButton
      and not self._window.isMaximized()
    ):
      self._window.move(event.globalPosition().toPoint() - self._drag_offset)
    super().mouseMoveEvent(event)

  def mouseReleaseEvent(self, event) -> None:
    self._drag_offset = None
    super().mouseReleaseEvent(event)

  def mouseDoubleClickEvent(self, event) -> None:
    if event.button() == Qt.MouseButton.LeftButton:
      self._toggle_maximize()
    super().mouseDoubleClickEvent(event)


class DocumentTab(QWidget):
  """Single open document: thumbnails + viewer."""

  def __init__(self, document: PdfDocument, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.document = document

    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)

    self.splitter = QSplitter(Qt.Orientation.Horizontal)

    left = QWidget()
    left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    left_layout = QVBoxLayout(left)
    left_layout.setContentsMargins(0, 0, 0, 0)

    header = QHBoxLayout()
    header.setSpacing(4)
    header.setContentsMargins(4, 4, 4, 4)
    header.addWidget(QLabel("썸네일"))
    header.addStretch()

    btn_width, btn_height = 28, 26
    self._thumb_level = DEFAULT_THUMB_SCALE_LEVEL
    self._thumb_size = thumb_scale_for_level(self._thumb_level)
    self.btn_thumb_zoom_out = QPushButton("-")
    self.btn_thumb_zoom_out.setFixedSize(btn_width, btn_height)
    self.btn_thumb_zoom_out.setToolTip("썸네일 축소")
    header.addWidget(self.btn_thumb_zoom_out)
    self.btn_thumb_zoom_in = QPushButton("+")
    self.btn_thumb_zoom_in.setFixedSize(btn_width, btn_height)
    self.btn_thumb_zoom_in.setToolTip("썸네일 확대")
    header.addWidget(self.btn_thumb_zoom_in)

    self.btn_rotate_ccw = QPushButton("↺")
    self.btn_rotate_ccw.setFixedSize(btn_width, btn_height)
    self.btn_rotate_ccw.setToolTip("선택 페이지 반시계 회전")
    header.addWidget(self.btn_rotate_ccw)
    self.btn_rotate_cw = QPushButton("↻")
    self.btn_rotate_cw.setFixedSize(btn_width, btn_height)
    self.btn_rotate_cw.setToolTip("선택 페이지 시계 회전")
    header.addWidget(self.btn_rotate_cw)
    self.btn_delete = QPushButton("🗑")
    self.btn_delete.setFixedSize(btn_width, btn_height)
    self.btn_delete.setToolTip("선택 페이지 삭제")
    header.addWidget(self.btn_delete)
    left_layout.addLayout(header)

    self.thumbnails = ThumbnailPanel()
    self.thumbnails.set_document(document)
    left_layout.addWidget(self.thumbnails)

    self.viewer = PageViewer()
    self.viewer.set_document(document)

    self.splitter.addWidget(left)
    self.splitter.addWidget(self.viewer)
    self.splitter.setStretchFactor(0, 0)
    self.splitter.setStretchFactor(1, 1)
    self.splitter.setChildrenCollapsible(False)
    self.splitter.setHandleWidth(APP_BORDER_WIDTH)
    self.splitter.setStyleSheet(
      f"QSplitter::handle:horizontal {{ background-color: {APP_WINDOW_BACKGROUND}; }}"
    )

    self._left_panel = left
    self._apply_panel_width_limits(set_default_size=True)
    if self.splitter.count() > 1:
      self.splitter.handle(0).setEnabled(False)
    layout.addWidget(self.splitter)

    self._connect_signals()

  def _connect_signals(self) -> None:
    self.thumbnails.page_selected.connect(self._on_thumb_selected)
    self.viewer.page_changed.connect(self._on_viewer_page_changed)
    self.thumbnails.insert_requested.connect(self._on_insert)
    self.thumbnails.pages_move_requested.connect(self._on_move_pages)
    self.thumbnails.delete_requested.connect(self._on_delete)
    self.thumbnails.rotate_requested.connect(self._on_rotate)
    self.thumbnails.export_pdf_requested.connect(self._on_export_pdf)
    self.thumbnails.export_images_requested.connect(self._on_export_images)
    self.thumbnails.blank_page_requested.connect(self._on_insert_blank)
    self.thumbnails.thumb_scale_changed.connect(
      lambda _scale: self._apply_panel_width_limits()
    )
    self.thumbnails.thumb_scale_changed.connect(
      lambda _scale: self._sync_thumb_zoom_buttons()
    )

    self.btn_thumb_zoom_in.clicked.connect(lambda: self._change_thumb_size(1))
    self.btn_thumb_zoom_out.clicked.connect(lambda: self._change_thumb_size(-1))
    self.btn_rotate_cw.clicked.connect(
      lambda: self._on_rotate(self.thumbnails.selected_indices() or [self.thumbnails.current_index()], 90)
    )
    self.btn_rotate_ccw.clicked.connect(
      lambda: self._on_rotate(self.thumbnails.selected_indices() or [self.thumbnails.current_index()], -90)
    )
    self.btn_delete.clicked.connect(
      lambda: self._on_delete(self.thumbnails.selected_indices())
    )

    self._setup_page_navigation_shortcuts()
    self._sync_thumb_zoom_buttons()

  def _change_thumb_size(self, step: int) -> None:
    if self.thumbnails.step_thumb_level(step):
      self._thumb_level = self.thumbnails.current_thumb_level()
      self._thumb_size = thumb_scale_for_level(self._thumb_level)
      self._sync_thumb_zoom_buttons()

  def _sync_thumb_zoom_buttons(self) -> None:
    level = self.thumbnails.current_thumb_level()
    max_level = len(THUMB_SCALE_LEVELS)
    self._thumb_level = level
    self._thumb_size = thumb_scale_for_level(level)
    self.btn_thumb_zoom_out.setEnabled(level > 1)
    self.btn_thumb_zoom_in.setEnabled(level < max_level)
    self.btn_thumb_zoom_out.setToolTip(f"썸네일 축소 ({level}/{max_level})")
    self.btn_thumb_zoom_in.setToolTip(f"썸네일 확대 ({level}/{max_level})")

  def _setup_page_navigation_shortcuts(self) -> None:
    prev_keys = (
      Qt.Key.Key_Left,
      Qt.Key.Key_Up,
      Qt.Key.Key_PageUp,
    )
    next_keys = (
      Qt.Key.Key_Right,
      Qt.Key.Key_Down,
      Qt.Key.Key_PageDown,
    )

    for key in prev_keys:
      shortcut = QShortcut(QKeySequence(key), self)
      shortcut.activated.connect(
        lambda: self.viewer.set_current_index(self.viewer.current_index() - 1)
      )

    for key in next_keys:
      shortcut = QShortcut(QKeySequence(key), self)
      shortcut.activated.connect(
        lambda: self.viewer.set_current_index(self.viewer.current_index() + 1)
      )

    first_page = QShortcut(QKeySequence("Ctrl+Shift+Left"), self)
    first_page.activated.connect(lambda: self.viewer.set_current_index(0))

    last_page = QShortcut(QKeySequence("Ctrl+Shift+Right"), self)
    last_page.activated.connect(
      lambda: self.viewer.set_current_index(max(0, self.document.page_count - 1))
    )

  def _apply_panel_width_limits(self, set_default_size: bool = False) -> None:
    fixed_w, _, _ = self.thumbnails.get_panel_width_range()
    self._left_panel.setFixedWidth(fixed_w)

    total = self.splitter.width()
    if total <= 0:
      total = self.width()
    if total <= 0:
      total = DEFAULT_WINDOW_WIDTH

    self.splitter.blockSignals(True)
    self.splitter.setSizes([fixed_w, max(200, total - fixed_w)])
    self.splitter.blockSignals(False)

    if self.splitter.count() > 1:
      self.splitter.handle(0).setEnabled(False)

  def resizeEvent(self, event) -> None:
    super().resizeEvent(event)
    self._apply_panel_width_limits()

  def _on_thumb_selected(self, index: int) -> None:
    self.viewer.blockSignals(True)
    self.viewer.set_current_index(index)
    self.viewer.blockSignals(False)

  def _on_viewer_page_changed(self, index: int) -> None:
    self.thumbnails.blockSignals(True)
    self.thumbnails.set_current_index(index)
    self.thumbnails.blockSignals(False)

  def refresh_all(self, keep_index: int | None = None, select_indices: list[int] | None = None) -> None:
    index = keep_index if keep_index is not None else self.thumbnails.current_index()
    self.thumbnails.refresh(index, select_indices)
    self.viewer.set_current_index(index)
    self.viewer.refresh()

  @staticmethod
  def _indices_after_delete(deleted: list[int], rows: list[int]) -> list[int]:
    deleted_set = set(deleted)
    adjusted: list[int] = []
    for row in sorted(rows):
      if row in deleted_set:
        continue
      shift = sum(1 for index in deleted_set if index < row)
      adjusted.append(row - shift)
    return adjusted

  def _on_move_pages(self, target_index: int, indices: list[int]) -> None:
    try:
      insert_at = self.document.move_pages_to_index(indices, target_index)
      if insert_at is None:
        return
      moved = list(range(insert_at, insert_at + len(indices)))
      self.thumbnails.refresh(keep_index=insert_at, select_indices=moved)
      self.viewer.set_current_index(insert_at)
      self.viewer.refresh()
    except Exception as exc:
      QMessageBox.critical(self, "페이지 이동 오류", str(exc))

  def _on_insert(self, index: int, paths: list[str]) -> None:
    if not paths:
      paths, _ = QFileDialog.getOpenFileNames(
        self,
        "삽입할 파일 선택",
        "",
        "지원 파일 (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp);;모든 파일 (*.*)",
      )
    if not paths:
      return
    try:
      was_empty = self.document.page_count == 0
      added = self.document.insert_files_at(index, paths)
      focus = index + added - 1 if added else index
      if added:
        self.thumbnails.insert_pages_at(index, added, keep_index=focus)
      self.viewer.set_current_index(focus)
      self.viewer.refresh()
      if added and was_empty:
        self.viewer.fit_height_when_ready()
    except Exception as exc:
      QMessageBox.critical(self, "삽입 오류", str(exc))

  def _on_insert_blank(self, index: int) -> None:
    try:
      was_empty = self.document.page_count == 0
      self.document.insert_blank_page_at(index)
      self.thumbnails.insert_pages_at(index, 1, keep_index=index, select_indices=[index])
      self.viewer.set_current_index(index)
      self.viewer.refresh()
      if was_empty:
        self.viewer.fit_height_when_ready()
    except Exception as exc:
      QMessageBox.critical(self, "빈 페이지 삽입 오류", str(exc))

  def _on_delete(self, indices: list[int]) -> None:
    if not indices:
      QMessageBox.information(self, "삭제", "삭제할 페이지를 선택하세요.")
      return
    reply = QMessageBox.question(
      self,
      "페이지 삭제",
      f"{len(indices)}개 페이지를 삭제하시겠습니까?",
      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
      return
    deleted = sorted(set(indices))
    keep = min(deleted)
    selected = self.thumbnails.selected_indices()
    self.document.delete_pages(deleted)
    if self.document.page_count == 0:
      self.thumbnails.refresh(0)
      self.viewer.set_current_index(0)
      self.viewer.refresh()
      return
    keep = min(keep, self.document.page_count - 1)
    remaining_selection = self._indices_after_delete(deleted, selected)
    self.thumbnails.remove_pages(deleted, keep_index=keep, select_indices=remaining_selection)
    self.viewer.set_current_index(keep)
    self.viewer.refresh()

  def _on_rotate(self, indices: list[int], degrees: int) -> None:
    if not indices:
      return
    self.document.rotate_pages(indices, degrees)
    self.thumbnails.invalidate_thumbnails(indices)
    if self.viewer.current_index() in indices:
      self.viewer.refresh()

  def _on_export_pdf(self, indices: list[int]) -> None:
    path, _ = QFileDialog.getSaveFileName(self, "페이지 보내기", "", "PDF (*.pdf)")
    if not path:
      return
    if not path.lower().endswith(".pdf"):
      path += ".pdf"
    try:
      self.document.export_pages_to_pdf(indices, path)
      QMessageBox.information(self, "보내기 완료", f"저장됨: {path}")
    except Exception as exc:
      QMessageBox.critical(self, "보내기 오류", str(exc))

  def _on_export_images(self, indices: list[int]) -> None:
    folder = QFileDialog.getExistingDirectory(self, "이미지 저장 폴더 선택")
    if not folder:
      return
    fmt, ok = QInputDialog.getItem(
      self, "이미지 형식", "형식 선택:", ["PNG", "JPEG"], 0, False
    )
    if not ok:
      return
    try:
      saved = self.document.export_pages_as_images(
        indices, folder, "png" if fmt == "PNG" else "jpg"
      )
      QMessageBox.information(self, "보내기 완료", f"{len(saved)}개 이미지 저장됨\n{folder}")
    except Exception as exc:
      QMessageBox.critical(self, "보내기 오류", str(exc))


class MainWindow(QMainWindow):
  def __init__(self) -> None:
    super().__init__()
    self.setObjectName("mainWindow")
    self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    self.setWindowFlags(
      Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
    )
    self.setWindowTitle(APP_TITLE)
    self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    self._centered_on_show = False

    app_icon = load_app_icon()
    if not app_icon.isNull():
      self.setWindowIcon(app_icon)

    self.tabs = QTabWidget()
    self.tabs.setTabsClosable(True)
    self.tabs.tabCloseRequested.connect(self._close_tab)
    self.tabs.currentChanged.connect(self._on_tab_changed)

    self._search_bar = TabSearchBar()
    self._search_bar.search_requested.connect(self._run_search)
    self._search_bar.search_next.connect(self._search_next)
    self._search_bar.search_prev.connect(self._search_prev)
    self.tabs.setCornerWidget(self._search_bar, Qt.Corner.TopRightCorner)

    self._content_frame = QWidget()
    content_layout = QVBoxLayout(self._content_frame)
    content_layout.setContentsMargins(
        APP_BORDER_WIDTH, 0, APP_BORDER_WIDTH, 0
    )
    content_layout.setSpacing(0)
    content_layout.addWidget(self.tabs)
    self.setCentralWidget(self._content_frame)

    self._search_hits: list[SearchHit] = []
    self._search_index = -1
    self._search_query = ""
    self._title_bar: TitleBar | None = None

    self._build_menu()
    self._setup_title_bar()
    self.setStatusBar(QStatusBar())
    self.statusBar().setSizeGripEnabled(True)
    self.statusBar().showMessage("준비")

    QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)
    QShortcut(QKeySequence("F3"), self, self._search_next)
    QShortcut(QKeySequence("Shift+F3"), self, self._search_prev)

    self._new_tab()
    QTimer.singleShot(0, self._update_search_bar_inset)

  def resizeEvent(self, event) -> None:
    super().resizeEvent(event)
    self._update_search_bar_inset()
    tab = self._current_tab()
    if tab is not None:
      tab._apply_panel_width_limits()

  def showEvent(self, event: QShowEvent) -> None:
    super().showEvent(event)
    if not self._centered_on_show:
      screen = QApplication.primaryScreen()
      if screen is not None:
        geo = screen.availableGeometry()
        self.move(
          geo.x() + max(0, (geo.width() - self.width()) // 2),
          geo.y() + max(0, (geo.height() - self.height()) // 2),
        )
      self._centered_on_show = True
    self._update_search_bar_inset()
    tab = self._current_tab()
    if tab is not None:
      QTimer.singleShot(0, tab._apply_panel_width_limits)
    QTimer.singleShot(0, lambda: apply_windows_window_icon(self))

  def _update_search_bar_inset(self) -> None:
    if self._title_bar is None:
      return
    tabs_right = self.tabs.mapToGlobal(QPoint(self.tabs.width(), 0)).x()
    close_center = self._title_bar.btn_close.mapToGlobal(
      QPoint(self._title_bar.btn_close.width() // 2, 0)
    ).x()
    self._search_bar.set_right_inset(int(tabs_right - close_center))

  def _current_tab(self) -> DocumentTab | None:
    widget = self.tabs.currentWidget()
    return widget if isinstance(widget, DocumentTab) else None

  def _build_menu(self) -> None:
    menu = self.menuBar().addMenu("파일(&F)")

    act_new = QAction("새 문서", self)
    act_new.setShortcut(QKeySequence.StandardKey.New)
    act_new.triggered.connect(self._new_tab)
    menu.addAction(act_new)

    act_open = QAction("열기...", self)
    act_open.setShortcut(QKeySequence.StandardKey.Open)
    act_open.triggered.connect(self._open_file)
    menu.addAction(act_open)

    menu.addSeparator()

    act_save = QAction("저장", self)
    act_save.setShortcut(QKeySequence.StandardKey.Save)
    act_save.triggered.connect(self._save)
    menu.addAction(act_save)

    act_save_as = QAction("다른 이름으로 저장...", self)
    act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
    act_save_as.triggered.connect(self._save_as)
    menu.addAction(act_save_as)

    menu.addSeparator()

    act_print = QAction("인쇄...", self)
    act_print.setShortcut(QKeySequence.StandardKey.Print)
    act_print.triggered.connect(self._print)
    menu.addAction(act_print)

    menu.addSeparator()

    act_exit = QAction("종료", self)
    act_exit.setShortcut(QKeySequence.StandardKey.Quit)
    act_exit.triggered.connect(self.close)
    menu.addAction(act_exit)

    edit_menu = self.menuBar().addMenu("편집(&E)")
    edit_menu.setObjectName("editMenu")
    edit_menu.setStyleSheet(
        """
        QMenu#editMenu::item {
            padding: 6px 24px 6px 11px;
        }
        QMenu#editMenu::item:first {
            padding: 0px;
        }
        QMenu#editMenu::item:first:selected {
            background-color: #e8f0fe;
        }
        """
    )
    act_reduce = QWidgetAction(self)
    reduce_btn = QPushButton("용량 줄이기...")
    reduce_btn.setFlat(True)
    reduce_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    reduce_btn.setStyleSheet(
        """
        QPushButton {
            color: #e57373;
            font-weight: bold;
            border: none;
            background: transparent;
            text-align: left;
            padding: 6px 24px 6px 11px;
            margin: 0px;
        }
        QPushButton:hover {
            background-color: #e8f0fe;
        }
        """
    )
    reduce_btn.clicked.connect(self._open_reduce_size_dialog)
    act_reduce.setDefaultWidget(reduce_btn)
    edit_menu.addAction(act_reduce)

    act_find = QAction("텍스트 검색...", self)
    act_find.setShortcut(QKeySequence.StandardKey.Find)
    act_find.triggered.connect(self._focus_search)
    edit_menu.addAction(act_find)

    act_delete = QAction("선택 페이지 삭제", self)
    act_delete.setShortcut(QKeySequence.StandardKey.Delete)
    act_delete.triggered.connect(self._delete_selected)
    edit_menu.addAction(act_delete)

    view_menu = self.menuBar().addMenu("보기(&V)")
    act_fit_width = QAction("너비 맞추기", self)
    act_fit_width.triggered.connect(lambda: self._current_tab() and self._current_tab().viewer.fit_width())
    view_menu.addAction(act_fit_width)
    act_fit_height = QAction("높이 맞추기", self)
    act_fit_height.triggered.connect(lambda: self._current_tab() and self._current_tab().viewer.fit_height())
    view_menu.addAction(act_fit_height)

    help_menu = self.menuBar().addMenu("도움말(&H)")
    act_about = QAction("About", self)
    act_about.triggered.connect(toggle_about_splash)
    help_menu.addAction(act_about)

  def _setup_title_bar(self) -> None:
    menu_bar = self.menuBar()
    menu_bar.setNativeMenuBar(False)

    chrome = QWidget()
    chrome_layout = QVBoxLayout(chrome)
    chrome_layout.setContentsMargins(
        APP_BORDER_WIDTH, APP_BORDER_WIDTH, APP_BORDER_WIDTH, 0
    )
    chrome_layout.setSpacing(0)
    self._title_bar = TitleBar(self)
    chrome_layout.addWidget(self._title_bar)
    chrome_layout.addWidget(menu_bar)
    self.setMenuWidget(chrome)

    self.setStyleSheet(
      f"""
      #mainWindow {{
        background-color: {APP_WINDOW_BACKGROUND};
      }}
      #appTitleBar {{
        background-color: #f3f3f3;
        border-bottom: 1px solid #d6d6d6;
      }}
      #mainWindow QMenuBar {{
        background-color: #f3f3f3;
      }}
      #mainWindow QStatusBar {{
        background-color: #f0f0f0;
        margin: 0px {APP_BORDER_WIDTH}px {APP_BORDER_WIDTH}px {APP_BORDER_WIDTH}px;
      }}
      #appTitleBar QPushButton {{
        border: none;
        border-radius: 0;
      }}
      #appTitleBar QPushButton:hover {{
        background-color: #e8e8e8;
      }}
      #appTitleBar QPushButton:pressed {{
        background-color: #d0d0d0;
      }}
      #tabSearchBar QLineEdit {{
        border: 1px solid #c8c8c8;
        border-radius: 3px;
        padding: 1px 6px;
        background: #ffffff;
      }}
      #tabSearchBar QPushButton {{
        border: 1px solid #c8c8c8;
        border-radius: 3px;
        background: #f8f8f8;
      }}
      #tabSearchBar QPushButton:hover {{
        background: #ececec;
      }}
      """
    )

  def _focus_search(self) -> None:
    self._search_bar.focus_search()

  def _on_tab_changed(self, _index: int) -> None:
    if self._search_query:
      self._run_search(self._search_query)
    else:
      self._clear_search_highlights()

  def _clear_search_highlights(self) -> None:
    tab = self._current_tab()
    if tab is not None:
      tab.viewer.clear_search_highlights()
    self._search_bar.set_search_status(0, 0)

  def _run_search(self, query: str | None = None) -> None:
    if query is None:
      query = self._search_bar.search_query()
    self._search_query = (query or "").strip()
    self._search_hits = []
    self._search_index = -1

    tab = self._current_tab()
    if not tab or not self._search_query:
      self._clear_search_highlights()
      if not self._search_query:
        self.statusBar().showMessage("준비")
      return

    self._search_hits = tab.document.search_text(self._search_query)
    if not self._search_hits:
      tab.viewer.clear_search_highlights()
      self._search_bar.set_search_status(0, 0)
      self.statusBar().showMessage(f'"{self._search_query}" 검색 결과 없음')
      return

    self._search_index = 0
    self._show_search_hit(self._search_index)
    self.statusBar().showMessage(
      f'"{self._search_query}" {len(self._search_hits)}건'
    )

  def _search_next(self) -> None:
    if not self._search_hits:
      self._run_search()
      return
    self._search_index = (self._search_index + 1) % len(self._search_hits)
    self._show_search_hit(self._search_index)

  def _search_prev(self) -> None:
    if not self._search_hits:
      self._run_search()
      return
    self._search_index = (self._search_index - 1) % len(self._search_hits)
    self._show_search_hit(self._search_index)

  def _show_search_hit(self, hit_index: int) -> None:
    tab = self._current_tab()
    if tab is None or not self._search_hits:
      return
    hit = self._search_hits[hit_index]
    page_hits = [item.rect for item in self._search_hits if item.page_index == hit.page_index]
    active_on_page = sum(
      1 for item in self._search_hits[: hit_index + 1] if item.page_index == hit.page_index
    ) - 1
    tab.viewer.show_search_result(
      hit.page_index,
      page_hits,
      active_on_page,
      focus_rect=hit.rect,
    )
    tab.thumbnails.blockSignals(True)
    tab.thumbnails.set_current_index(hit.page_index)
    tab.thumbnails.blockSignals(False)
    self._search_bar.set_search_status(hit_index + 1, len(self._search_hits))

  def _add_tab(self, document: PdfDocument, title: str | None = None) -> DocumentTab:
    tab = DocumentTab(document)
    name = title or document.display_name
    index = self.tabs.addTab(tab, name)
    self.tabs.setCurrentIndex(index)
    return tab

  def _new_tab(self) -> None:
    self._add_tab(PdfDocument(), "새 문서")

  def _open_file(self) -> None:
    path, _ = QFileDialog.getOpenFileName(self, "PDF 열기", "", "PDF (*.pdf)")
    if not path:
      return
    try:
      doc = PdfDocument()
      doc.open_file(path)
      self._add_tab(doc, os.path.basename(path))
      self.statusBar().showMessage(f"열림: {path}")
    except Exception as exc:
      QMessageBox.critical(self, "열기 오류", str(exc))

  def _save(self) -> None:
    tab = self._current_tab()
    if tab:
      self._save_document_tab(tab)

  def _save_as(self) -> None:
    tab = self._current_tab()
    if tab:
      self._save_document_tab_as(tab)

  def _save_document_tab(self, tab: DocumentTab) -> bool:
    index = self.tabs.indexOf(tab)
    if tab.document.source_path:
      try:
        tab.document.save()
        if index >= 0:
          self.tabs.setTabText(index, tab.document.display_name)
        self.statusBar().showMessage(f"저장됨: {tab.document.source_path}")
        return True
      except Exception as exc:
        QMessageBox.critical(self, "저장 오류", str(exc))
        return False
    return self._save_document_tab_as(tab)

  def _save_document_tab_as(self, tab: DocumentTab) -> bool:
    index = self.tabs.indexOf(tab)
    path, _ = QFileDialog.getSaveFileName(self, "다른 이름으로 저장", "", "PDF (*.pdf)")
    if not path:
      return False
    if not path.lower().endswith(".pdf"):
      path += ".pdf"
    try:
      tab.document.save(path)
      if index >= 0:
        self.tabs.setTabText(index, tab.document.display_name)
      self.statusBar().showMessage(f"저장됨: {path}")
      return True
    except Exception as exc:
      QMessageBox.critical(self, "저장 오류", str(exc))
      return False

  def _handle_close_save_choice(self, tab: DocumentTab, choice: CloseSaveChoice) -> bool:
    """Return True when the tab may be closed."""
    if choice == CloseSaveChoice.CANCEL:
      return False
    if choice == CloseSaveChoice.DISCARD:
      return True
    if choice == CloseSaveChoice.SAVE_AS:
      return self._save_document_tab_as(tab)
    return False

  def _print(self) -> None:
    tab = self._current_tab()
    if not tab or tab.document.page_count == 0:
      QMessageBox.information(self, "인쇄", "인쇄할 문서가 없습니다.")
      return

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog = QPrintDialog(printer, self)
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
      return

    try:
      with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
      tab.document.save(tmp_path)
      self._print_pdf_windows(tmp_path)
      Path(tmp_path).unlink(missing_ok=True)
    except Exception as exc:
      QMessageBox.critical(self, "인쇄 오류", str(exc))

  def _print_pdf_windows(self, pdf_path: str) -> None:
    if sys.platform == "win32":
      os.startfile(pdf_path, "print")
    else:
      subprocess.run(["lp", pdf_path], check=False)

  def _open_reduce_size_dialog(self) -> None:
    tab = self._current_tab()
    if tab is None or tab.document.page_count == 0:
      QMessageBox.information(self, "용량 줄이기", "페이지가 있는 문서를 열어주세요.")
      return
    tab.document.pause_rendering()
    accepted = False
    dialog: ReduceSizeDialog | None = None
    try:
      dialog = ReduceSizeDialog(tab.document, parent=self)
      accepted = dialog.exec() == QDialog.DialogCode.Accepted
    finally:
      tab.document.resume_rendering()
    if not accepted or dialog is None:
      return
    tab.thumbnails.refresh()
    tab.viewer.refresh()
    self.statusBar().showMessage(
      f"용량 줄이기 완료: {format_file_size(dialog.result_before)}"
      f" → {format_file_size(dialog.result_after)}"
    )

  def _delete_selected(self) -> None:
    tab = self._current_tab()
    if tab:
      tab._on_delete(tab.thumbnails.selected_indices())

  def _close_tab(self, index: int) -> None:
    widget = self.tabs.widget(index)
    if isinstance(widget, DocumentTab) and widget.document.modified:
      self.tabs.setCurrentIndex(index)
      reply = _ask_save_modified(
        self,
        "저장 확인",
        "변경 사항을 저장하시겠습니까?",
      )
      if not self._handle_close_save_choice(widget, reply):
        return
    self.tabs.removeTab(index)
    if self.tabs.count() == 0:
      self._new_tab()

  def closeEvent(self, event) -> None:
    for index in range(self.tabs.count()):
      widget = self.tabs.widget(index)
      if isinstance(widget, DocumentTab) and widget.document.modified:
        self.tabs.setCurrentIndex(index)
        reply = _ask_save_modified(
          self,
          "저장 확인",
          f"'{self.tabs.tabText(index)}'의 변경 사항을 저장하시겠습니까?",
        )
        if not self._handle_close_save_choice(widget, reply):
          event.ignore()
          return
    event.accept()


def run() -> None:
  init_platform()
  app = QApplication(sys.argv)
  app.setApplicationName("Tiny PDF Editor")
  app.setApplicationDisplayName(APP_TITLE)
  app_icon = load_app_icon()
  if not app_icon.isNull():
    app.setWindowIcon(app_icon)

  splash = show_loading_splash(app_icon)
  started = time.monotonic()
  window = MainWindow()
  elapsed_ms = int((time.monotonic() - started) * 1000)

  finish_loading_splash(splash, elapsed_ms, window.show)
  sys.exit(app.exec())
