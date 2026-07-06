"""Application main window."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
  QAction,
  QCursor,
  QDesktopServices,
  QIcon,
  QKeySequence,
  QShortcut,
  QShowEvent,
)
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from pdf_editor.document import (
  PdfDocument,
  PdfPasswordRequired,
  PdfPasswordRejected,
  SearchHit,
  SUPPORTED_FILE_FILTER,
  configure_mupdf_messages,
  format_file_size,
)
from pdf_editor.page_clipboard import PageClipboard
from pdf_editor.password_dialog import SetPasswordDialog, prompt_pdf_password
from pdf_editor.print_utils import print_document
from pdf_editor.page_viewer import PageViewer
from pdf_editor.reduce_size_dialog import ReduceSizeDialog
from pdf_editor.resources import (
  apply_windows_window_icon,
  init_platform,
  load_app_icon,
)
from pdf_editor.splash_screen import (
  finish_loading_splash,
  show_loading_splash,
  toggle_about_splash,
)
from pdf_editor.highlight_panel import HighlightPanel
from pdf_editor.left_side_nav import (
  LEFT_SIDE_NAV_WIDTH,
  SIDE_PANEL_DIVIDER_COLOR,
  LeftSideNavBar,
  SideNavTab,
)
from pdf_editor.side_panel_header import (
  PANEL_HEADER_BTN_HEIGHT,
  PANEL_HEADER_BTN_WIDTH,
  SidePanelHeaderBar,
  make_panel_divider,
)
from pdf_editor.thumbnail_panel import (
  DEFAULT_THUMB_SCALE_LEVEL,
  THUMB_PANEL_EXTRA_WIDTH,
  THUMB_SCALE_LEVELS,
  ThumbnailPanel,
  thumb_scale_for_level,
)


from pdf_editor.version import (
  APP_NAME,
  AUTHOR_LINK_TEXT,
  AUTHOR_URL,
  __version__,
  titled_name,
  version_label,
)
from pdf_editor.windows_file_assoc import (
  is_pdf_association_registered,
  is_windows as is_windows_platform,
  open_pdf_default_apps_settings,
  register_pdf_association,
  unregister_pdf_association,
)

APP_BORDER_COLOR = "#333333"
APP_WINDOW_BACKGROUND = "#eeeeee"
APP_BORDER_WIDTH = 1
DEFAULT_WINDOW_WIDTH = 1024 + LEFT_SIDE_NAV_WIDTH + THUMB_PANEL_EXTRA_WIDTH
DEFAULT_WINDOW_HEIGHT = 900
MIN_WINDOW_WIDTH = 520 + LEFT_SIDE_NAV_WIDTH + THUMB_PANEL_EXTRA_WIDTH
MIN_WINDOW_HEIGHT = 480
_TAB_BASENAME_MAX_LEN = 24
_REDUCE_MENU_BTN_STYLE = """
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


def _truncate_middle(text: str, max_len: int) -> str:
    if max_len <= 0 or len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    keep = max_len - 3
    front = (keep + 1) // 2
    back = keep // 2
    return f"{text[:front]}...{text[-back:]}"


def _tab_title_for_filename(filename: str, *, extra_count: int = 0) -> str:
    suffix = f" 외 {extra_count}개" if extra_count > 0 else ""
    max_name_len = max(8, _TAB_BASENAME_MAX_LEN - len(suffix))
    return f"{_truncate_middle(filename, max_name_len)}{suffix}"


def _tab_title_for_opened_files(opened: list[str]) -> str:
    first_name = os.path.basename(opened[0])
    if len(opened) == 1:
        return _tab_title_for_filename(first_name)
    return _tab_title_for_filename(first_name, extra_count=len(opened) - 1)


def parse_launch_paths(argv: list[str]) -> list[str]:
    """Return supported file paths passed on the command line (e.g. Windows file association)."""
    paths: list[str] = []
    seen: set[str] = set()
    for arg in argv[1:]:
        if not arg or arg.startswith("-"):
            continue
        path = str(Path(arg))
        if not os.path.isfile(path):
            continue
        if not PdfDocument.is_supported_file(path):
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


class CloseSaveChoice(str, Enum):
    SAVE_AS = "save_as"
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


_CLOSE_SAVE_DIALOG_BTN_HEIGHT = 36
_CLOSE_SAVE_DIALOG_MESSAGE_SPACING = 10

_INSERT_INITIAL_BATCH = 5
_INSERT_CONTINUE_BATCH = 20


def _style_close_save_dialog_button(
    button: QPushButton,
    *,
    background: str,
    hover: str,
    pressed: str,
    text_color: str = "#333333",
    border_color: str = "#cccccc",
) -> None:
    button.setFixedHeight(_CLOSE_SAVE_DIALOG_BTN_HEIGHT)
    button.setStyleSheet(
        "QPushButton {"
        f" min-height: {_CLOSE_SAVE_DIALOG_BTN_HEIGHT}px;"
        " padding: 8px 16px;"
        f" border: 1px solid {border_color};"
        " border-radius: 3px;"
        f" background-color: {background};"
        f" color: {text_color};"
        " }"
        f"QPushButton:hover {{ background-color: {hover}; border: 1px solid {border_color}; }}"
        f"QPushButton:pressed {{ background-color: {pressed}; border: 1px solid {border_color}; }}"
    )


def _ask_save_modified(parent: QWidget, title: str, text: str) -> CloseSaveChoice:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 12, 24, 20)
    layout.setSpacing(_CLOSE_SAVE_DIALOG_MESSAGE_SPACING)

    message = QLabel(text)
    message.setWordWrap(False)
    message.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    message.setStyleSheet("QLabel { padding: 0; font-size: 13px; }")
    layout.addWidget(message, 0, Qt.AlignmentFlag.AlignLeft)

    button_row = QHBoxLayout()
    button_row.setSpacing(8)
    button_row.setContentsMargins(0, 0, 0, 0)

    save_as_button = QPushButton("다른 이름으로 저장하고 닫기")
    save_button = QPushButton("저장하고 닫기")
    discard_button = QPushButton("저장하지 않고 닫기")
    cancel_button = QPushButton("취소")
    result = CloseSaveChoice.CANCEL

    def choose_save_as() -> None:
        nonlocal result
        result = CloseSaveChoice.SAVE_AS
        dialog.accept()

    def choose_save() -> None:
        nonlocal result
        result = CloseSaveChoice.SAVE
        dialog.accept()

    def choose_discard() -> None:
        nonlocal result
        result = CloseSaveChoice.DISCARD
        dialog.accept()

    save_as_button.clicked.connect(choose_save_as)
    save_button.clicked.connect(choose_save)
    discard_button.clicked.connect(choose_discard)
    cancel_button.clicked.connect(dialog.reject)

    _style_close_save_dialog_button(
        save_as_button,
        background="#dbeafe",
        hover="#bfdbfe",
        pressed="#93c5fd",
    )
    _style_close_save_dialog_button(
        save_button,
        background="#dcfce7",
        hover="#bbf7d0",
        pressed="#86efac",
    )
    _style_close_save_dialog_button(
        discard_button,
        background="#fde8e6",
        hover="#fbd0cb",
        pressed="#f5b8b2",
    )
    _style_close_save_dialog_button(
        cancel_button,
        background="#f3f4f6",
        hover="#e5e7eb",
        pressed="#d1d5db",
    )

    button_row.addWidget(discard_button)
    button_row.addWidget(save_button)
    button_row.addWidget(save_as_button)
    button_row.addWidget(cancel_button)
    layout.addLayout(button_row)

    dialog.adjustSize()
    dialog.setMinimumWidth(dialog.sizeHint().width())

    save_as_button.setDefault(True)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        return result
    return CloseSaveChoice.CANCEL


def open_pdf_document(parent: QWidget, path: str) -> PdfDocument | None:
    password: str | None = None
    wrong = False
    while True:
        try:
            doc = PdfDocument()
            doc.open_file(path, password=password)
            return doc
        except PdfPasswordRejected:
            wrong = True
            password = prompt_pdf_password(parent, path, wrong=True)
            if password is None:
                return None
        except PdfPasswordRequired:
            password = prompt_pdf_password(parent, path, wrong=wrong)
            if password is None:
                return None
            wrong = False


def resolve_pdf_password_for(parent: QWidget) -> Callable[[str, bool], str | None]:
    return lambda path, wrong: prompt_pdf_password(parent, path, wrong=wrong)


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

    layout.addSpacing(8)
    self.search_result_label = QLabel("검색 결과 : ")
    layout.addWidget(self.search_result_label)

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
  """Title row: icon, app name, and window controls."""

  def __init__(self, window: QMainWindow) -> None:
    super().__init__(window)
    self._window = window
    self._drag_offset: QPoint | None = None
    self._maximized_drag = False
    self._press_local_y = 0.0
    self._normal_frame_geo = None
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
    icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    layout.addWidget(icon_label)

    title = QLabel(APP_NAME)
    title.setStyleSheet("font-weight: 600;")
    title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    layout.addWidget(title)

    version = QLabel(version_label())
    version.setStyleSheet("color: #666666; font-size: 12px; padding-top: 1px;")
    version.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    layout.addWidget(version)

    layout.addStretch(1)

    style = window.style()
    self.btn_close = QPushButton()
    self.btn_close.setObjectName("titleBarCloseButton")
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
      self._normal_frame_geo = self._window.frameGeometry()
      self._window.showMaximized()

  def _restore_from_maximized_at(self, local_y: float) -> None:
    if self._normal_frame_geo is not None:
      width = self._normal_frame_geo.width()
    else:
      normal_geo = self._window.normalGeometry()
      width = normal_geo.width() if normal_geo.isValid() else self._window.width()

    cursor = QCursor.pos()
    self._window.showNormal()
    self._window.move(
      cursor.x() - width // 2,
      cursor.y() - int(local_y),
    )
    self._drag_offset = QCursor.pos() - self._window.frameGeometry().topLeft()

  def _release_mouse_grab(self) -> None:
    if self.mouseGrabber() is self:
      self.releaseMouse()

  def mousePressEvent(self, event) -> None:
    if event.button() == Qt.MouseButton.LeftButton:
      global_pos = event.globalPosition().toPoint()
      if self._window.isMaximized():
        self._maximized_drag = True
        self._press_local_y = event.position().y()
        self._drag_offset = None
        self.grabMouse()
      else:
        self._maximized_drag = False
        self._drag_offset = global_pos - self._window.frameGeometry().topLeft()
    super().mousePressEvent(event)

  def mouseMoveEvent(self, event) -> None:
    if event.buttons() & Qt.MouseButton.LeftButton:
      if self._window.isMaximized() and self._maximized_drag:
        self._restore_from_maximized_at(self._press_local_y)
        self._maximized_drag = False
      elif self._drag_offset is not None and not self._window.isMaximized():
        self._window.move(QCursor.pos() - self._drag_offset)
    super().mouseMoveEvent(event)

  def mouseReleaseEvent(self, event) -> None:
    self._drag_offset = None
    self._maximized_drag = False
    self._release_mouse_grab()
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
    self._markup_entry_count = len(document.get_text_markup_entries())
    self._file_insert_token = 0

    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)

    self.splitter = QSplitter(Qt.Orientation.Horizontal)

    left = QWidget()
    left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    left_layout = QHBoxLayout(left)
    left_layout.setContentsMargins(0, 0, 0, 0)
    left_layout.setSpacing(0)

    self.side_nav = LeftSideNavBar()
    self.content_stack = QStackedWidget()

    thumb_page = QWidget()
    thumb_layout = QVBoxLayout(thumb_page)
    thumb_layout.setContentsMargins(0, 0, 0, 0)
    thumb_layout.setSpacing(0)

    thumb_layout.addWidget(make_panel_divider())

    header_bar = SidePanelHeaderBar()
    header = header_bar.row_layout
    header.addWidget(QLabel("  썸네일"))
    header.addStretch()

    self._thumb_level = DEFAULT_THUMB_SCALE_LEVEL
    self._thumb_size = thumb_scale_for_level(self._thumb_level)
    self.btn_thumb_zoom_out = QPushButton("-")
    self.btn_thumb_zoom_out.setFixedSize(PANEL_HEADER_BTN_WIDTH, PANEL_HEADER_BTN_HEIGHT)
    self.btn_thumb_zoom_out.setToolTip("썸네일 축소")
    header.addWidget(self.btn_thumb_zoom_out)
    self.btn_thumb_zoom_in = QPushButton("+")
    self.btn_thumb_zoom_in.setFixedSize(PANEL_HEADER_BTN_WIDTH, PANEL_HEADER_BTN_HEIGHT)
    self.btn_thumb_zoom_in.setToolTip("썸네일 확대")
    header.addWidget(self.btn_thumb_zoom_in)

    self.btn_rotate_ccw = QPushButton("↺")
    self.btn_rotate_ccw.setFixedSize(PANEL_HEADER_BTN_WIDTH, PANEL_HEADER_BTN_HEIGHT)
    self.btn_rotate_ccw.setToolTip("선택 페이지 반시계 회전")
    header.addWidget(self.btn_rotate_ccw)
    self.btn_rotate_cw = QPushButton("↻")
    self.btn_rotate_cw.setFixedSize(PANEL_HEADER_BTN_WIDTH, PANEL_HEADER_BTN_HEIGHT)
    self.btn_rotate_cw.setToolTip("선택 페이지 시계 회전")
    header.addWidget(self.btn_rotate_cw)
    self.btn_delete = QPushButton("🗑")
    self.btn_delete.setFixedSize(PANEL_HEADER_BTN_WIDTH, PANEL_HEADER_BTN_HEIGHT)
    self.btn_delete.setToolTip("선택 페이지 삭제")
    header.addWidget(self.btn_delete)
    thumb_layout.addWidget(header_bar)

    self.thumbnails = ThumbnailPanel()
    self.thumbnails.set_document(document)
    thumb_layout.addWidget(self.thumbnails, 1)
    thumb_layout.addWidget(make_panel_divider())

    self.highlight_panel = HighlightPanel()
    self.highlight_panel.set_document(document)

    self.content_stack.addWidget(thumb_page)
    self.content_stack.addWidget(self.highlight_panel)

    left_layout.addWidget(self.side_nav)
    left_layout.addWidget(self.content_stack, 1)

    self.side_nav.tab_changed.connect(self._on_side_nav_tab_changed)

    self.viewer = PageViewer()
    self.viewer.set_document(document)

    self.splitter.addWidget(left)
    self.splitter.addWidget(self.viewer)
    self.splitter.setStretchFactor(0, 0)
    self.splitter.setStretchFactor(1, 1)
    self.splitter.setChildrenCollapsible(False)
    self.splitter.setHandleWidth(APP_BORDER_WIDTH)
    self.splitter.setStyleSheet(
      f"QSplitter::handle:horizontal {{ background-color: {SIDE_PANEL_DIVIDER_COLOR}; }}"
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
    self.viewer.page_canvas.text_highlight_added.connect(self._on_text_highlight_added)
    self.highlight_panel.entry_selected.connect(self._on_highlight_panel_entry_selected)
    self.highlight_panel.markup_changed.connect(self._on_text_highlight_added)
    self.viewer.page_canvas.markup_clicked.connect(self._on_markup_clicked)
    self.thumbnails.insert_requested.connect(self._on_insert)
    self.thumbnails.pages_move_requested.connect(self._on_move_pages)
    self.thumbnails.delete_requested.connect(self._on_delete)
    self.thumbnails.rotate_requested.connect(self._on_rotate)
    self.thumbnails.export_pdf_requested.connect(self._on_export_pdf)
    self.thumbnails.export_images_requested.connect(self._on_export_images)
    self.thumbnails.blank_page_requested.connect(self._on_insert_blank)
    self.thumbnails.undo_requested.connect(self._on_undo)
    self.thumbnails.redo_requested.connect(self._on_redo)
    self.thumbnails.copy_pages_requested.connect(self._on_copy_pages)
    self.thumbnails.cut_pages_requested.connect(self._on_cut_pages)
    self.thumbnails.paste_pages_requested.connect(self._on_paste_pages)
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

  def _restore_highlights_panel_viewport(self) -> None:
    self.highlight_panel.refresh()
    current = self.viewer.current_index()
    QTimer.singleShot(0, lambda idx=current: self.highlight_panel.scroll_to_current_context(idx))

  def _on_side_nav_tab_changed(self, index: int) -> None:
    self.content_stack.setCurrentIndex(index)
    if index == int(SideNavTab.THUMBNAILS):
      QTimer.singleShot(0, self.thumbnails._restore_after_tab_show)
    elif index == int(SideNavTab.HIGHLIGHTS):
      self._restore_highlights_panel_viewport()

  def _switch_to_highlights_panel(self) -> None:
    if self.side_nav.current_tab() == SideNavTab.HIGHLIGHTS:
      return
    self.side_nav.set_current_tab(SideNavTab.HIGHLIGHTS)
    self.content_stack.setCurrentIndex(int(SideNavTab.HIGHLIGHTS))
    self._restore_highlights_panel_viewport()

  def _page_indices_for_clipboard(self) -> list[int]:
    return self.thumbnails.copy_indices()

  def _should_copy_viewer_text(self) -> bool:
    canvas = self.viewer.page_canvas
    if not canvas.selected_text():
      return False
    focus = QApplication.focusWidget()
    if focus is None:
      return False
    if isinstance(focus, QLineEdit):
      return False
    return focus is canvas or self.viewer.isAncestorOf(focus)

  def _on_copy_pages_shortcut(self) -> None:
    if self._should_copy_viewer_text():
      self.viewer.page_canvas._copy_selection()
      return
    indices = self._page_indices_for_clipboard()
    if indices:
      self._on_copy_pages(indices)

  def _on_cut_pages_shortcut(self) -> None:
    indices = self._page_indices_for_clipboard()
    if indices:
      self._on_cut_pages(indices)

  def _on_paste_pages_shortcut(self) -> None:
    if not PageClipboard.has_pages():
      return
    insert_at = self.thumbnails.resolve_paste_index()
    self._on_paste_pages(insert_at)

  def _on_copy_pages(self, indices: list[int]) -> None:
    if not indices:
      return
    try:
      valid = sorted({index for index in indices if 0 <= index < self.document.page_count})
      if not valid:
        return
      pdf_bytes = self.document.extract_pages_to_bytes(valid)
      PageClipboard.set_pages(pdf_bytes, len(valid))
      self._notify_clipboard_changed()
    except Exception as exc:
      QMessageBox.critical(self, "복사 오류", str(exc))

  def _on_cut_pages(self, indices: list[int]) -> None:
    if not indices:
      return
    try:
      valid = sorted({index for index in indices if 0 <= index < self.document.page_count})
      if not valid:
        return
      pdf_bytes = self.document.extract_pages_to_bytes(valid)
      PageClipboard.set_pages(pdf_bytes, len(valid))
      self._apply_page_deletion(valid)
      self._notify_clipboard_changed()
    except Exception as exc:
      QMessageBox.critical(self, "잘라내기 오류", str(exc))

  def _on_paste_pages(self, insert_at: int) -> None:
    payload = PageClipboard.get_payload()
    if payload is None:
      return
    try:
      page_count_before = self.document.page_count
      was_empty = page_count_before == 0
      insert_at = max(0, min(insert_at, page_count_before))
      added = self.document.insert_pages_from_bytes(insert_at, payload.pdf_bytes)
      if not added:
        return
      focus = self._insert_focus_index(
        insert_at,
        added,
        was_empty=was_empty,
        page_count_before=page_count_before,
      )
      self.thumbnails.insert_pages_at(
        insert_at,
        added,
        keep_index=focus,
        select_indices=[focus],
      )
      self.thumbnails._set_paste_anchor(insert_at + added)
      self.go_to_page(focus, fit_page=was_empty)
      self._notify_history_changed()
      self._notify_clipboard_changed()
    except Exception as exc:
      QMessageBox.critical(self, "붙여넣기 오류", str(exc))

  def _apply_page_deletion(self, indices: list[int]) -> None:
    deleted = sorted(set(indices))
    keep = min(deleted)
    selected = self.thumbnails.selected_indices()
    self.document.delete_pages(deleted)
    if self.document.page_count == 0:
      self.thumbnails.refresh(0)
      self.viewer.set_current_index(0)
      self.viewer.refresh()
      self._notify_history_changed()
      return
    keep = min(keep, self.document.page_count - 1)
    remaining_selection = self._indices_after_delete(deleted, selected)
    self.thumbnails.remove_pages(deleted, keep_index=keep, select_indices=remaining_selection)
    self.viewer.set_current_index(keep)
    self.viewer.refresh()
    self._notify_history_changed()

  def _notify_clipboard_changed(self) -> None:
    window = self.window()
    if isinstance(window, MainWindow):
      window._update_edit_actions()

  def _on_undo(self) -> None:
    if not self.document.undo():
      return
    index = self.thumbnails.current_index()
    if self.document.page_count > 0:
      index = max(0, min(index, self.document.page_count - 1))
    self.refresh_all(keep_index=index)
    self._notify_history_changed()

  def _on_redo(self) -> None:
    if not self.document.redo():
      return
    index = self.thumbnails.current_index()
    if self.document.page_count > 0:
      index = max(0, min(index, self.document.page_count - 1))
    self.refresh_all(keep_index=index)
    self._notify_history_changed()

  def _notify_history_changed(self) -> None:
    window = self.window()
    if isinstance(window, MainWindow):
      window._update_edit_actions()

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
    thumb_w, _, _ = self.thumbnails.get_panel_width_range()
    fixed_w = LEFT_SIDE_NAV_WIDTH + thumb_w
    if self._left_panel.width() != fixed_w:
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

  def _on_text_highlight_added(self) -> None:
    before_count = self._markup_entry_count
    self.highlight_panel.refresh()
    self.viewer.refresh()
    self._notify_history_changed()
    self._markup_entry_count = len(self.document.get_text_markup_entries())
    if before_count == 0 and self._markup_entry_count > 0:
      if self.side_nav.current_tab() == SideNavTab.THUMBNAILS:
        self._switch_to_highlights_panel()

  def refresh_all(self, keep_index: int | None = None, select_indices: list[int] | None = None) -> None:
    index = keep_index if keep_index is not None else self.thumbnails.current_index()
    self.thumbnails.refresh(index, select_indices)
    self.highlight_panel.refresh()
    self.viewer.set_current_index(index)
    self.viewer.refresh()
    self._markup_entry_count = len(self.document.get_text_markup_entries())

  def go_to_page(self, index: int, *, fit_page: bool = False) -> None:
    if self.document.page_count == 0:
      return
    index = max(0, min(index, self.document.page_count - 1))
    self.thumbnails.set_current_index(index)
    if self.viewer.current_index() != index:
      self.viewer.set_current_index(index)
    else:
      self.viewer.refresh()
    if fit_page:
      self.viewer.fit_page_when_ready()

  def _on_markup_clicked(self, entry) -> None:
    if self.side_nav.current_tab() == SideNavTab.THUMBNAILS:
      self._switch_to_highlights_panel()
    self.highlight_panel.select_entry(entry)
    self.thumbnails.blockSignals(True)
    self.thumbnails.set_current_index(entry.page_index)
    self.thumbnails.blockSignals(False)

  def _on_highlight_panel_entry_selected(self, entry) -> None:
    if self.side_nav.current_tab() == SideNavTab.THUMBNAILS:
      self._switch_to_highlights_panel()
    self.viewer.select_markup_entry(entry)
    self.thumbnails.blockSignals(True)
    self.thumbnails.set_current_index(entry.page_index)
    self.thumbnails.blockSignals(False)

  @staticmethod
  def _insert_focus_index(
    insert_at: int,
    added: int,
    *,
    was_empty: bool,
    page_count_before: int,
  ) -> int:
    if added <= 0:
      return insert_at
    if was_empty or insert_at < page_count_before:
      return insert_at
    return insert_at + added - 1

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
      self._notify_history_changed()
    except Exception as exc:
      QMessageBox.critical(self, "페이지 이동 오류", str(exc))

  def _on_insert(self, index: int, paths: list[str]) -> None:
    if not paths:
      paths, _ = QFileDialog.getOpenFileNames(
        self,
        "삽입할 파일 선택",
        "",
        SUPPORTED_FILE_FILTER,
      )
    if not paths:
      return
    page_count_before = self.document.page_count
    was_empty = page_count_before == 0
    if len(paths) <= _INSERT_INITIAL_BATCH:
      try:
        added = self.document.insert_files_at(
          index,
          paths,
          resolve_pdf_password=resolve_pdf_password_for(self),
        )
        if added:
          focus = self._insert_focus_index(
            index,
            added,
            was_empty=was_empty,
            page_count_before=page_count_before,
          )
          self.thumbnails.insert_pages_at(
            index,
            added,
            keep_index=focus,
            select_indices=[focus],
          )
          self.go_to_page(focus, fit_page=was_empty)
          self.highlight_panel.refresh()
        self._notify_history_changed()
      except Exception as exc:
        QMessageBox.critical(self, "삽입 오류", str(exc))
      return

    self._file_insert_token += 1
    token = self._file_insert_token
    try:
      added = self._insert_files_batch(
        index,
        paths[:_INSERT_INITIAL_BATCH],
        was_empty=was_empty,
        page_count_before=page_count_before,
        record_undo=True,
        fit_page=was_empty,
        focus=None,
        token=token,
      )
      remaining = paths[_INSERT_INITIAL_BATCH:]
      if remaining:
        focus = self.thumbnails.current_index()
        self.viewer.show_busy_message("파일 불러오는 중...")
        QTimer.singleShot(
          0,
          lambda ni=index + added, rp=remaining, f=focus: self._continue_insert_files(
            ni,
            rp,
            page_count_before=page_count_before,
            focus=f,
            token=token,
          ),
        )
      elif added:
        self._finish_insert_files(token)
    except Exception as exc:
      self._file_insert_token += 1
      self.viewer.hide_busy_message()
      QMessageBox.critical(self, "삽입 오류", str(exc))

  def _insert_files_batch(
    self,
    index: int,
    paths: list[str],
    *,
    was_empty: bool,
    page_count_before: int,
    record_undo: bool,
    fit_page: bool,
    focus: int | None,
    token: int,
  ) -> int:
    if token != self._file_insert_token:
      return 0
    added = self.document.insert_files_at(
      index,
      paths,
      record_undo=record_undo,
      resolve_pdf_password=resolve_pdf_password_for(self),
    )
    if added <= 0:
      return 0
    if focus is None:
      focus = self._insert_focus_index(
        index,
        added,
        was_empty=was_empty,
        page_count_before=page_count_before,
      )
    self.thumbnails.insert_pages_at(
      index,
      added,
      keep_index=focus,
      select_indices=[focus],
    )
    if fit_page:
      self.go_to_page(focus, fit_page=True)
    return added

  def _continue_insert_files(
    self,
    index: int,
    paths: list[str],
    *,
    page_count_before: int,
    focus: int,
    token: int,
  ) -> None:
    if token != self._file_insert_token or not paths:
      return
    batch = paths[:_INSERT_CONTINUE_BATCH]
    rest = paths[_INSERT_CONTINUE_BATCH:]
    try:
      added = self._insert_files_batch(
        index,
        batch,
        was_empty=False,
        page_count_before=page_count_before,
        record_undo=False,
        fit_page=False,
        focus=focus,
        token=token,
      )
      loaded = self.document.page_count - page_count_before
      self.viewer.show_busy_message(f"파일 불러오는 중... {loaded}페이지")
      if rest and token == self._file_insert_token:
        QTimer.singleShot(
          0,
          lambda: self._continue_insert_files(
            index + added,
            rest,
            page_count_before=page_count_before,
            focus=focus,
            token=token,
          ),
        )
        return
      self._finish_insert_files(token)
    except Exception as exc:
      self._file_insert_token += 1
      self.viewer.hide_busy_message()
      QMessageBox.critical(self, "삽입 오류", str(exc))
      self._notify_history_changed()

  def _finish_insert_files(self, token: int) -> None:
    if token != self._file_insert_token:
      return
    self.viewer.hide_busy_message()
    self.highlight_panel.refresh()
    self._notify_history_changed()

  def _on_insert_blank(self, index: int) -> None:
    try:
      was_empty = self.document.page_count == 0
      self.document.insert_blank_page_at(index)
      self.thumbnails.insert_pages_at(index, 1, keep_index=index, select_indices=[index])
      self.viewer.set_current_index(index)
      self.viewer.refresh()
      if was_empty:
        self.viewer.fit_page_when_ready()
      self._notify_history_changed()
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
    self._apply_page_deletion(indices)

  def _on_rotate(self, indices: list[int], degrees: int) -> None:
    if not indices:
      return
    self.document.rotate_pages(indices, degrees)
    self.thumbnails.invalidate_thumbnails(indices)
    if self.viewer.current_index() in indices:
      self.viewer.refresh()
    self._notify_history_changed()

  def _on_export_pdf(self, indices: list[int]) -> None:
    if not indices:
      QMessageBox.information(self, "새 파일로 저장", "저장할 페이지를 선택하세요.")
      return
    stem = Path(self.document.display_name).stem
    source = self.document.source_path
    default_path = str(Path(source).with_name(f"{stem}.pdf")) if source else f"{stem}.pdf"
    path, _ = QFileDialog.getSaveFileName(
      self, "새 파일로 저장", default_path, "PDF (*.pdf)"
    )
    if not path:
      return
    if not path.lower().endswith(".pdf"):
      path += ".pdf"
    try:
      self.document.export_pages_to_pdf(indices, path)
      QMessageBox.information(self, "새 파일로 저장", f"저장됨: {path}")
    except Exception as exc:
      QMessageBox.critical(self, "새 파일로 저장", str(exc))

  def _on_export_images(self, indices: list[int]) -> None:
    if not indices:
      QMessageBox.information(self, "이미지로 저장", "저장할 페이지를 선택하세요.")
      return
    folder = QFileDialog.getExistingDirectory(self, "이미지로 저장")
    if not folder:
      return
    try:
      saved = self.document.export_pages_as_images(indices, folder)
      QMessageBox.information(
        self, "이미지로 저장", f"{len(saved)}개 이미지 저장됨\n{folder}"
      )
    except Exception as exc:
      QMessageBox.critical(self, "이미지로 저장", str(exc))


class MainWindow(QMainWindow):
  def __init__(self, launch_paths: list[str] | None = None) -> None:
    super().__init__()
    self.setObjectName("mainWindow")
    self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    self.setWindowFlags(
      Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
    )
    self.setWindowTitle(titled_name())
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
    self._setup_status_credit()
    self.statusBar().setSizeGripEnabled(True)
    self.statusBar().showMessage("준비")

    QShortcut(QKeySequence("F3"), self, self._search_next)
    QShortcut(QKeySequence("Shift+F3"), self, self._search_prev)

    self._pending_launch_paths = list(launch_paths or [])
    self._optimize_running = False
    if self._pending_launch_paths:
      QTimer.singleShot(0, self._open_pending_launch_paths)
    else:
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

  def _update_edit_actions(self) -> None:
    tab = self._current_tab()
    can_undo = tab.document.can_undo() if tab else False
    can_redo = tab.document.can_redo() if tab else False
    can_copy = bool(tab and tab._page_indices_for_clipboard()) if tab else False
    can_paste = PageClipboard.has_pages()
    if hasattr(self, "_act_undo"):
      self._act_undo.setEnabled(can_undo)
    if hasattr(self, "_act_redo"):
      self._act_redo.setEnabled(can_redo)
    if hasattr(self, "_act_copy"):
      self._act_copy.setEnabled(can_copy)
    if hasattr(self, "_act_cut"):
      self._act_cut.setEnabled(can_copy)
    if hasattr(self, "_act_paste"):
      self._act_paste.setEnabled(can_paste)
    can_password = bool(tab and tab.document.page_count > 0)
    if hasattr(self, "_act_set_password"):
      self._act_set_password.setEnabled(can_password)
    if hasattr(self, "_act_remove_password"):
      self._act_remove_password.setEnabled(
        can_password and tab.document.has_password_protection()
      )
    can_add = bool(tab and tab.document.page_count > 0)
    if hasattr(self, "_act_add"):
      self._act_add.setEnabled(can_add)

  def _copy_current_tab(self) -> None:
    tab = self._current_tab()
    if tab is not None:
      tab._on_copy_pages_shortcut()

  def _cut_current_tab(self) -> None:
    tab = self._current_tab()
    if tab is not None:
      tab._on_cut_pages_shortcut()

  def _paste_current_tab(self) -> None:
    tab = self._current_tab()
    if tab is not None:
      tab._on_paste_pages_shortcut()

  def _undo_current_tab(self) -> None:
    tab = self._current_tab()
    if tab is not None:
      tab._on_undo()

  def _redo_current_tab(self) -> None:
    tab = self._current_tab()
    if tab is not None:
      tab._on_redo()

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

    self._act_add = QAction("추가...", self)
    self._act_add.setEnabled(False)
    self._act_add.triggered.connect(self._add_files)
    menu.addAction(self._act_add)

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

    if is_windows_platform():
      menu.addSeparator()
      act_assoc = QAction("PDF 파일 연결...", self)
      act_assoc.triggered.connect(self._manage_pdf_file_association)
      menu.addAction(act_assoc)

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
        QMenu#editMenu::item:nth-child(3) {
            padding: 0px;
        }
        QMenu#editMenu::item:nth-child(3):selected {
            background-color: #e8f0fe;
        }
        """
    )
    self._act_undo = QAction("되돌리기(&U)", self)
    self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
    self._act_undo.triggered.connect(self._undo_current_tab)
    edit_menu.addAction(self._act_undo)

    self._act_redo = QAction("재실행(&R)", self)
    self._act_redo.setShortcut(QKeySequence.StandardKey.Redo)
    self._act_redo.triggered.connect(self._redo_current_tab)
    edit_menu.addAction(self._act_redo)

    edit_menu.addSeparator()
    self._act_copy = QAction("복사(&C)", self)
    self._act_copy.setShortcut(QKeySequence.StandardKey.Copy)
    self._act_copy.triggered.connect(self._copy_current_tab)
    edit_menu.addAction(self._act_copy)

    self._act_cut = QAction("잘라내기(&T)", self)
    self._act_cut.setShortcut(QKeySequence.StandardKey.Cut)
    self._act_cut.triggered.connect(self._cut_current_tab)
    edit_menu.addAction(self._act_cut)

    self._act_paste = QAction("붙여넣기(&P)", self)
    self._act_paste.setShortcut(QKeySequence.StandardKey.Paste)
    self._act_paste.triggered.connect(self._paste_current_tab)
    edit_menu.addAction(self._act_paste)

    edit_menu.addSeparator()

    self._act_set_password = QAction("비밀번호 설정...", self)
    self._act_set_password.triggered.connect(self._set_document_password)
    edit_menu.addAction(self._act_set_password)

    self._act_remove_password = QAction("비밀번호 제거", self)
    self._act_remove_password.triggered.connect(self._clear_document_password)
    edit_menu.addAction(self._act_remove_password)

    edit_menu.addSeparator()
    act_reduce = QWidgetAction(self)
    reduce_btn = QPushButton("용량 줄이기...")
    reduce_btn.setFlat(True)
    reduce_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    reduce_btn.setStyleSheet(_REDUCE_MENU_BTN_STYLE)
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
    act_fit_page = QAction("화면 맞추기", self)
    act_fit_page.triggered.connect(lambda: self._current_tab() and self._current_tab().viewer.fit_page())
    view_menu.addAction(act_fit_page)

    help_menu = self.menuBar().addMenu("도움말(&H)")
    act_about = QAction("About", self)
    act_about.triggered.connect(toggle_about_splash)
    help_menu.addAction(act_about)

  def _setup_status_credit(self) -> None:
    credit = QLabel(f'<a href="{AUTHOR_URL}">{AUTHOR_LINK_TEXT}</a>')
    credit.setObjectName("statusCredit")
    credit.setTextFormat(Qt.TextFormat.RichText)
    credit.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    credit.setOpenExternalLinks(False)
    credit.linkActivated.connect(
      lambda href: QDesktopServices.openUrl(QUrl(href))
    )
    credit.setCursor(Qt.CursorShape.PointingHandCursor)
    self.statusBar().addPermanentWidget(credit)

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
      #statusCredit {{
        color: #666666;
        font-size: 11px;
        padding-right: 4px;
      }}
      #statusCredit a {{
        color: #666666;
        text-decoration: none;
      }}
      #statusCredit a:hover {{
        color: #1a73e8;
        text-decoration: underline;
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
      #appTitleBar QPushButton#titleBarCloseButton:hover {{
        background-color: #eea0a0;
      }}
      #appTitleBar QPushButton#titleBarCloseButton:pressed {{
        background-color: #e07070;
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
    self._update_edit_actions()
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

  def _add_files(self) -> None:
    tab = self._current_tab()
    if tab is None or tab.document.page_count == 0:
      return
    before = tab.document.page_count
    tab._on_insert(before, [])
    after = tab.document.page_count
    if after > before:
      tab.go_to_page(after - 1)
      self.statusBar().showMessage(f"{after - before}페이지를 추가했습니다.")

  def _open_pending_launch_paths(self) -> None:
    paths = self._pending_launch_paths
    self._pending_launch_paths = []
    if not self._open_paths(paths) and self.tabs.count() == 0:
      self._new_tab()

  def _open_paths(self, paths: list[str]) -> bool:
    if not paths:
      return False

    if len(paths) == 1:
      path = paths[0]
      if not PdfDocument.is_supported_file(path):
        QMessageBox.critical(self, "열기 오류", "지원하지 않는 파일 형식입니다.")
        return False
      try:
        doc = open_pdf_document(self, path)
        if doc is None:
          return False
        tab = self._add_tab(doc, _tab_title_for_filename(os.path.basename(path)))
        QTimer.singleShot(0, lambda: tab.go_to_page(0, fit_page=True))
        self._update_edit_actions()
        self.statusBar().showMessage(f"열림: {path}")
        return True
      except Exception as exc:
        QMessageBox.critical(self, "열기 오류", str(exc))
        return False

    doc = PdfDocument()
    opened: list[str] = []
    failed: list[tuple[str, str]] = []
    for path in paths:
      if not PdfDocument.is_supported_file(path):
        failed.append((path, "지원하지 않는 파일 형식입니다."))
        continue
      try:
        added = doc.insert_files_at(
          doc.page_count,
          [path],
          resolve_pdf_password=resolve_pdf_password_for(self),
        )
        if added == 0:
          failed.append((path, "페이지를 추가할 수 없습니다."))
        else:
          opened.append(path)
      except Exception as exc:
        failed.append((path, str(exc)))

    if not opened:
      details = "\n".join(f"{os.path.basename(path)}: {message}" for path, message in failed)
      QMessageBox.critical(self, "열기 오류", details or "열 수 있는 파일이 없습니다.")
      doc._doc.close()
      return False

    doc._source_path = (
      str(Path(opened[0]).resolve()) if len(opened) == 1 else None
    )
    doc._modified = False
    doc.clear_history()

    tab = self._add_tab(doc, _tab_title_for_opened_files(opened))
    QTimer.singleShot(0, lambda: tab.go_to_page(0, fit_page=True))
    self._update_edit_actions()
    self.statusBar().showMessage(f"{len(opened)}개 파일, {doc.page_count}페이지를 열었습니다.")

    if failed:
      details = "\n".join(f"{os.path.basename(path)}: {message}" for path, message in failed)
      QMessageBox.warning(
        self,
        "일부 파일을 열 수 없음",
        f"{len(failed)}개 파일을 열지 못했습니다.\n\n{details}",
      )
    return True

  def _open_file(self) -> None:
    paths, _ = QFileDialog.getOpenFileNames(self, "파일 열기", "", SUPPORTED_FILE_FILTER)
    if not paths:
      return
    self._open_paths(paths)

  def _manage_pdf_file_association(self) -> None:
    if not is_windows_platform():
      return

    registered = is_pdf_association_registered()
    status = "등록됨" if registered else "등록 안 됨"
    box = QMessageBox(self)
    box.setWindowTitle("PDF 파일 연결")
    box.setText(
      f"현재 상태: {status}\n\n"
      f"등록 경로:\n{sys.executable}\n\n"
      "「연결 등록」: Windows 연결 프로그램 목록에 추가\n"
      "「연결 해제」: 위 경로로 등록한 항목을 레지스트리에서 삭제\n"
      "「Windows 설정」: PDF 기본 앱 설정 열기"
    )
    btn_register = box.addButton("연결 등록", QMessageBox.ButtonRole.AcceptRole)
    btn_unregister = box.addButton("연결 해제", QMessageBox.ButtonRole.DestructiveRole)
    btn_settings = box.addButton("Windows 설정", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.setDefaultButton(btn_register)
    box.exec()
    clicked = box.clickedButton()
    if clicked is None or clicked == box.button(QMessageBox.StandardButton.Close):
      return

    if clicked == btn_settings:
      open_pdf_default_apps_settings()
      return

    if clicked == btn_unregister:
      if not registered:
        QMessageBox.information(
          self,
          "PDF 파일 연결",
          "현재 이 실행 파일로 등록된 연결이 없습니다.",
        )
        return
      reply = QMessageBox.question(
        self,
        "PDF 파일 연결",
        "이 PC에 등록된 Tiny PDF Editor PDF 연결을 삭제하시겠습니까?\n\n"
        "Windows에서 PDF 기본 앱으로 지정해 두었다면 "
        "설정 → 앱 → 기본 앱에서 PDF 기본 앱도 다른 프로그램으로 바꿔 주세요.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
      )
      if reply != QMessageBox.StandardButton.Yes:
        return
      try:
        unregister_pdf_association()
      except OSError as exc:
        QMessageBox.critical(self, "PDF 파일 연결", str(exc))
        return
      QMessageBox.information(self, "PDF 파일 연결", "연결 해제가 완료되었습니다.")
      return

    try:
      register_pdf_association()
    except OSError as exc:
      QMessageBox.critical(self, "PDF 파일 연결", str(exc))
      return

    follow = QMessageBox.question(
      self,
      "PDF 파일 연결",
      "연결 등록이 완료되었습니다.\n\n"
      "Windows 설정에서 PDF 기본 앱을 「Tiny PDF Editor」로 선택하면 "
      "「항상」 옵션으로 열 수 있습니다.\n\n"
      "Windows 기본 앱 설정을 열까요?",
      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
      QMessageBox.StandardButton.Yes,
    )
    if follow == QMessageBox.StandardButton.Yes:
      open_pdf_default_apps_settings()

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
        tab.highlight_panel.refresh()
        self.statusBar().showMessage(f"저장됨: {tab.document.source_path}")
        return True
      except Exception as exc:
        QMessageBox.critical(self, "저장 오류", str(exc))
        return False
    return self._save_document_tab_as(tab)

  def _save_document_tab_as(self, tab: DocumentTab) -> bool:
    index = self.tabs.indexOf(tab)
    default_path = tab.document.source_path or ""
    if not default_path:
      title = tab.document.display_name
      if title and title != "새 문서":
        default_path = title if title.lower().endswith(".pdf") else f"{Path(title).stem}.pdf"
      else:
        default_path = "새 문서.pdf"
    path, _ = QFileDialog.getSaveFileName(
      self, "다른 이름으로 저장", default_path, "PDF (*.pdf)"
    )
    if not path:
      return False
    if not path.lower().endswith(".pdf"):
      path += ".pdf"
    try:
      tab.document.save(path)
      if index >= 0:
        self.tabs.setTabText(index, tab.document.display_name)
      tab.highlight_panel.refresh()
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
    if choice == CloseSaveChoice.SAVE:
      return self._save_document_tab(tab)
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
      print_document(tab.document, printer)
    except Exception as exc:
      QMessageBox.critical(self, "인쇄 오류", str(exc))

  def _set_document_password(self) -> None:
    tab = self._current_tab()
    if tab is None or tab.document.page_count == 0:
      QMessageBox.information(self, "PDF 비밀번호", "페이지가 있는 문서를 열어주세요.")
      return
    dialog = SetPasswordDialog(self)
    if dialog.exec() != QDialog.DialogCode.Accepted:
      return
    try:
      user_password, owner_password = dialog.passwords()
      tab.document.set_password_protection(user_password, owner_password)
      self._update_edit_actions()
      self.statusBar().showMessage(
        "비밀번호가 설정되었습니다. 저장하면 암호가 적용된 PDF로 저장됩니다."
      )
    except Exception as exc:
      QMessageBox.critical(self, "PDF 비밀번호", str(exc))

  def _clear_document_password(self) -> None:
    tab = self._current_tab()
    if tab is None or not tab.document.has_password_protection():
      return
    reply = QMessageBox.question(
      self,
      "PDF 비밀번호",
      "비밀번호를 제거하시겠습니까?\n저장하면 암호 없는 PDF로 저장됩니다.",
      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
      QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
      return
    tab.document.clear_password_protection()
    self._update_edit_actions()
    self.statusBar().showMessage(
      "비밀번호가 제거되었습니다. 저장하면 암호 없는 PDF로 저장됩니다."
    )

  def _open_reduce_size_dialog(self) -> None:
    tab = self._current_tab()
    if tab is None or tab.document.page_count == 0:
      QMessageBox.information(self, "용량 줄이기", "페이지가 있는 문서를 열어주세요.")
      return
    if self._optimize_running:
      QMessageBox.information(
        self,
        "용량 줄이기",
        "이미 용량 줄이기 작업이 진행 중입니다.",
      )
      return
    dialog = ReduceSizeDialog(tab.document, parent=self)
    if dialog.exec() != QDialog.DialogCode.Accepted:
      return
    options = dialog.selected_options()
    source_bytes = tab.document.save_to_bytes()

    tab.document.pause_rendering()
    tab.viewer.show_log_panel()
    tab.viewer.append_log_line("> 용량 줄이기 작업을 시작합니다...")
    tab.viewer.show_busy_message("용량 줄이기 진행 중...")
    self._optimize_running = True
    QTimer.singleShot(
      0,
      lambda: self._run_optimize(tab, options, source_bytes),
    )

  def _run_optimize(self, tab: DocumentTab, options, source_bytes: bytes) -> None:
    before = len(source_bytes)
    last_image_log = {"text": ""}
    applied = False

    def on_status(message: str) -> None:
      tab.viewer.append_log_line(message)

    def on_image_progress(current: int, total: int) -> None:
      text = f"  이미지 재압축 중... {current}/{total}"
      if text != last_image_log["text"]:
        last_image_log["text"] = text
        tab.viewer.append_log_line(text)

    try:
      payload = PdfDocument.build_optimized_payload(
        source_bytes,
        options,
        status_callback=on_status,
        image_progress=on_image_progress,
      )
      after = len(payload)
      tab.document.apply_reduced_payload(payload)
      applied = True
      tab.viewer.append_log_line(
        f"완료: {format_file_size(before)} → {format_file_size(after)}"
      )
      self.statusBar().showMessage(
        f"용량 줄이기 완료: {format_file_size(before)}"
        f" → {format_file_size(after)}"
      )
    except Exception as exc:
      tab.viewer.append_log_line(f"오류: {exc}")
      QMessageBox.critical(self, "용량 줄이기 오류", str(exc))
    finally:
      self._optimize_running = False
      tab.document.resume_rendering()
      tab.viewer.hide_busy_message()
      if applied:
        index = tab.thumbnails.current_index()
        tab.refresh_all(keep_index=index)
        self._update_edit_actions()

  def _delete_selected(self) -> None:
    tab = self._current_tab()
    if not tab:
      return
    if (
      tab.side_nav.current_tab() == SideNavTab.HIGHLIGHTS
      and tab.highlight_panel.try_remove_selected()
    ):
      return
    if tab.viewer.try_remove_selected_highlight():
      return
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
    if isinstance(widget, DocumentTab):
      widget._file_insert_token += 1
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


def run(argv: list[str] | None = None) -> None:
  init_platform()
  configure_mupdf_messages()
  app = QApplication(sys.argv)
  app.setApplicationName(APP_NAME)
  app.setApplicationDisplayName(titled_name())
  app.setApplicationVersion(__version__)
  app_icon = load_app_icon()
  if not app_icon.isNull():
    app.setWindowIcon(app_icon)

  launch_paths = parse_launch_paths(argv if argv is not None else sys.argv)

  splash = show_loading_splash(app_icon)
  started = time.monotonic()
  window = MainWindow(launch_paths=launch_paths)
  elapsed_ms = int((time.monotonic() - started) * 1000)

  finish_loading_splash(splash, elapsed_ms, window.show)
  sys.exit(app.exec())
