"""PDF merge dialog: pick files, reorder, choose output, then merge."""

from __future__ import annotations

import os
import re
from pathlib import Path

import fitz
from PyQt6.QtCore import QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.app_settings import AppSettings, default_downloads_folder
from pdf_editor.document import (
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    SUPPORTED_FILE_FILTER,
    PdfDocument,
)
from pdf_editor.pixmap_utils import pixmap_from_fitz

_ACCENT = "#7eb8e8"
_ACCENT_HOVER = "#5aa3e0"
_ACCENT_PRESSED = "#3d8fd4"
_ACCENT_SOFT = "#e8f4fc"
_PATH_ROLE = Qt.ItemDataRole.UserRole
_DEFAULT_NAME = "병합"
_PREVIEW_MAX_WIDTH = 240
_MERGE_INITIAL_BATCH = 5
_MERGE_CONTINUE_BATCH = 20


def _sanitize_filename(name: str) -> str:
    base = name.strip() or _DEFAULT_NAME
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).rstrip(" .")
    return cleaned or _DEFAULT_NAME


def _page_count_for_path(path: str) -> int | None:
    try:
        ext = Path(path).suffix.lower()
        if ext in PDF_EXTENSIONS:
            with fitz.open(path) as doc:
                return doc.page_count
        if ext in IMAGE_EXTENSIONS:
            return 1
    except Exception:
        return None
    return None


def _thumbnail_for_path(path: str, max_width: int = _PREVIEW_MAX_WIDTH) -> QPixmap | None:
    """Render the first page (or image) as a QPixmap for the sidebar preview."""
    try:
        ext = Path(path).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return None
            return pixmap.scaled(
                max_width,
                max_width * 3,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        if ext not in PDF_EXTENSIONS:
            return None
        with fitz.open(path) as doc:
            if doc.page_count < 1:
                return None
            page = doc[0]
            width = max(1.0, float(page.rect.width))
            zoom = max_width / width
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            return pixmap_from_fitz(pix)
    except Exception:
        return None


def _paths_from_mime(mime: QMimeData) -> list[str]:
    paths: list[str] = []
    if not mime.hasUrls():
        return paths
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path and PdfDocument.is_supported_file(path):
            paths.append(path)
    return paths


class _MergeFileList(QListWidget):
    """Reorderable file list that also accepts external file drops."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mergeFileList")
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setAlternatingRowColors(True)
        self.setSpacing(2)
        self.setDragEnabled(True)
        self.setStyleSheet(
            """
            QListWidget#mergeFileList {
                border: 1px dashed #c8c8c8;
                border-radius: 6px;
                background: #ffffff;
                padding: 6px;
            }
            QListWidget#mergeFileList::item {
                padding: 8px 10px;
                border-radius: 4px;
            }
            QListWidget#mergeFileList::item:selected {
                background: #e8f4fc;
                color: #222222;
            }
            """
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _paths_from_mime(event.mimeData())
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class _DropEmptyState(QFrame):
    """Dashed drop zone shown when the merge list is empty."""

    files_dropped = pyqtSignal(list)
    add_files_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mergeDropZone")
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            """
            QFrame#mergeDropZone {
                border: 1px dashed #c8c8c8;
                border-radius: 6px;
                background: #fafafa;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        hint = QLabel("파일을 여기로 끌어다 놓습니다.")
        hint_font = QFont()
        hint_font.setPointSize(11)
        hint.setFont(hint_font)
        hint.setStyleSheet("color: #555555; border: none;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self._add_btn = QToolButton()
        self._add_btn.setText("파일 추가")
        self._add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._add_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet(
            f"""
            QToolButton {{
                background-color: {_ACCENT};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 18px;
                font-weight: 600;
                min-width: 110px;
            }}
            QToolButton:hover {{ background-color: {_ACCENT_HOVER}; }}
            QToolButton:pressed {{ background-color: {_ACCENT_PRESSED}; }}
            QToolButton::menu-button {{
                border-left: 1px solid rgba(255,255,255,0.35);
                width: 22px;
            }}
            """
        )
        self._add_btn.clicked.connect(self.add_files_clicked.emit)
        layout.addWidget(self._add_btn, 0, Qt.AlignmentFlag.AlignCenter)

    def set_add_menu(self, menu) -> None:
        self._add_btn.setMenu(menu)
        self._add_btn.setDefaultAction(None)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _paths_from_mime(event.mimeData())
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class MergePdfDialog(QDialog):
    """Collect files and output options, then merge into one PDF."""

    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
        *,
        resolve_pdf_password=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._resolve_pdf_password = resolve_pdf_password
        self._output_path: str | None = None
        self._merge_token = 0
        self._merge_doc: PdfDocument | None = None
        self._merge_progress: QProgressDialog | None = None
        self._merge_target = ""
        self._merge_insert_at = 0
        self._merge_pages = 0
        self._merge_files_done = 0
        self._merge_total_files = 0
        self.setWindowTitle("PDF 병합")
        self.setMinimumSize(820, 520)
        self.resize(900, 560)
        self._build_ui()
        self._sync_empty_state()

    def output_path(self) -> str | None:
        return self._output_path

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 16)
        body_layout.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(10)
        title = QLabel("PDF 병합")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        left.addWidget(title)

        self._stack_host = QWidget()
        stack_layout = QVBoxLayout(self._stack_host)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(0)

        self._empty_state = _DropEmptyState()
        self._empty_state.files_dropped.connect(self._add_paths)
        self._empty_state.add_files_clicked.connect(self._pick_files)

        self._list = _MergeFileList()
        self._list.files_dropped.connect(self._add_paths)
        self._list.itemSelectionChanged.connect(self._update_preview)

        list_wrap = QVBoxLayout()
        list_wrap.setContentsMargins(0, 0, 0, 0)
        list_wrap.setSpacing(8)
        list_toolbar = QHBoxLayout()
        list_toolbar.addStretch(1)
        self._list_add_btn = QPushButton("파일 추가")
        self._list_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._list_add_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {_ACCENT};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}
            QPushButton:pressed {{ background-color: {_ACCENT_PRESSED}; }}
            """
        )
        self._list_add_btn.clicked.connect(self._pick_files)
        self._list_remove_btn = QPushButton("선택 제거")
        self._list_remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._list_remove_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #ffffff;
                color: {_ACCENT_PRESSED};
                border: 1px solid {_ACCENT};
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{ background-color: {_ACCENT_SOFT}; }}
            """
        )
        self._list_remove_btn.clicked.connect(self._remove_selected)
        list_toolbar.addWidget(self._list_remove_btn)
        list_toolbar.addWidget(self._list_add_btn)
        list_wrap.addLayout(list_toolbar)
        list_wrap.addWidget(self._list, 1)
        self._list_panel = QWidget()
        self._list_panel.setLayout(list_wrap)

        stack_layout.addWidget(self._empty_state)
        stack_layout.addWidget(self._list_panel)
        left.addWidget(self._stack_host, 1)

        hint = QLabel("목록에서 파일을 위·아래로 드래그해 병합 순서를 바꿀 수 있습니다.")
        hint.setStyleSheet("color: #777777; font-size: 11px;")
        left.addWidget(hint)
        body_layout.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.setAlignment(Qt.AlignmentFlag.AlignTop)

        name_label = QLabel("파일 이름")
        name_label.setStyleSheet("font-weight: 600;")
        right.addWidget(name_label)
        self._name_edit = QLineEdit(_DEFAULT_NAME)
        self._name_edit.setPlaceholderText("병합 파일 이름")
        right.addWidget(self._name_edit)

        loc_label = QLabel("저장 위치")
        loc_label.setStyleSheet("font-weight: 600; margin-top: 8px;")
        right.addWidget(loc_label)
        self._loc_combo = QComboBox()
        self._loc_combo.addItem("폴더 지정", "folder")
        right.addWidget(self._loc_combo)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        folder = self._settings.merge_save_folder
        if not Path(folder).is_dir():
            folder = default_downloads_folder()
            self._settings.merge_save_folder = folder
        self._folder_edit.setText(folder)
        self._folder_edit.setToolTip(folder)
        browse = QPushButton("...")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse_folder)
        path_row.addWidget(self._folder_edit, 1)
        path_row.addWidget(browse)
        right.addLayout(path_row)

        preview_label = QLabel("미리 보기")
        preview_label.setStyleSheet("font-weight: 600; margin-top: 8px;")
        right.addWidget(preview_label)

        self._preview_frame = QFrame()
        self._preview_frame.setObjectName("mergePreviewFrame")
        self._preview_frame.setMinimumHeight(220)
        self._preview_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_frame.setStyleSheet(
            """
            QFrame#mergePreviewFrame {
                background: #f5f5f5;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
            }
            """
        )
        preview_layout = QVBoxLayout(self._preview_frame)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        self._preview_image = QLabel()
        self._preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_image.setMinimumSize(120, 160)
        self._preview_image.setStyleSheet("border: none; background: transparent; color: #888;")
        self._preview_image.setText("선택된 파일이 없습니다.")
        self._preview_image.setWordWrap(True)
        preview_layout.addWidget(self._preview_image, 1)
        right.addWidget(self._preview_frame, 1)

        body_layout.addLayout(right, 1)
        root.addWidget(body, 1)

        footer = QFrame()
        footer.setObjectName("mergeFooter")
        footer.setStyleSheet(
            """
            QFrame#mergeFooter {
                background: #f3f3f3;
                border-top: 1px solid #e0e0e0;
            }
            """
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 10)
        footer_layout.addStretch(1)
        self._apply_btn = QPushButton("적용")
        self._apply_btn.setEnabled(False)
        self._apply_btn.setMinimumWidth(100)
        self._apply_btn.setMinimumHeight(34)
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {_ACCENT};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 22px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}
            QPushButton:disabled {{
                background-color: #d0d0d0;
                color: #888888;
            }}
            """
        )
        self._apply_btn.clicked.connect(self._apply)
        footer_layout.addWidget(self._apply_btn)
        root.addWidget(footer)

        add_menu = self._build_add_menu()
        self._empty_state.set_add_menu(add_menu)

    def _build_add_menu(self):
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("파일 추가...", self._pick_files)
        menu.addAction("폴더에서 PDF 추가...", self._pick_folder_pdfs)
        return menu

    def _file_paths(self) -> list[str]:
        paths: list[str] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is None:
                continue
            path = item.data(_PATH_ROLE)
            if isinstance(path, str):
                paths.append(path)
        return paths

    def _sync_empty_state(self) -> None:
        has_files = self._list.count() > 0
        self._empty_state.setVisible(not has_files)
        self._list_panel.setVisible(has_files)
        self._apply_btn.setEnabled(has_files)
        self._list_remove_btn.setEnabled(has_files)
        if has_files and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)
        self._update_preview()

    def _add_paths(self, paths: list[str]) -> None:
        existing = {os.path.normcase(p) for p in self._file_paths()}
        added = 0
        first_new: QListWidgetItem | None = None
        for path in paths:
            if not PdfDocument.is_supported_file(path):
                continue
            key = os.path.normcase(os.path.abspath(path))
            if key in existing:
                continue
            existing.add(key)
            pages = _page_count_for_path(path)
            label = os.path.basename(path)
            if pages is not None:
                label = f"{label}  ({pages}페이지)"
            item = QListWidgetItem(label)
            item.setData(_PATH_ROLE, str(Path(path).resolve()))
            item.setToolTip(str(Path(path).resolve()))
            self._list.addItem(item)
            if first_new is None:
                first_new = item
            added += 1
        if added and self._name_edit.text().strip() in ("", _DEFAULT_NAME):
            first = Path(self._file_paths()[0]).stem
            self._name_edit.setText(f"{first}_병합")
        if first_new is not None:
            self._list.setCurrentItem(first_new)
        self._sync_empty_state()

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "병합할 파일 선택",
            self._folder_edit.text() or default_downloads_folder(),
            SUPPORTED_FILE_FILTER,
        )
        if paths:
            self._add_paths(paths)

    def _pick_folder_pdfs(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "PDF가 있는 폴더 선택",
            self._folder_edit.text() or default_downloads_folder(),
        )
        if not folder:
            return
        paths = sorted(
            str(p)
            for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in PDF_EXTENSIONS
        )
        if not paths:
            QMessageBox.information(self, "PDF 병합", "선택한 폴더에 PDF 파일이 없습니다.")
            return
        self._add_paths(paths)

    def _remove_selected(self) -> None:
        for item in list(self._list.selectedItems()):
            row = self._list.row(item)
            self._list.takeItem(row)
        self._sync_empty_state()

    def _update_preview(self) -> None:
        item = self._list.currentItem()
        if item is None:
            selected = self._list.selectedItems()
            item = selected[0] if selected else None
        if item is None:
            self._preview_image.clear()
            self._preview_image.setText("선택된 파일이 없습니다.")
            return
        path = item.data(_PATH_ROLE)
        if not isinstance(path, str) or not path:
            self._preview_image.clear()
            self._preview_image.setText("미리보기를 만들 수 없습니다.")
            return
        frame_w = max(120, self._preview_frame.width() - 24)
        pixmap = _thumbnail_for_path(path, max_width=min(_PREVIEW_MAX_WIDTH, frame_w))
        if pixmap is None or pixmap.isNull():
            self._preview_image.clear()
            self._preview_image.setText("미리보기를 만들 수 없습니다.")
            return
        self._preview_image.setText("")
        self._preview_image.setPixmap(pixmap)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "저장 폴더 선택",
            self._folder_edit.text() or default_downloads_folder(),
        )
        if not folder:
            return
        self._folder_edit.setText(folder)
        self._folder_edit.setToolTip(folder)
        self._settings.merge_save_folder = folder

    def _resolved_output_path(self) -> str | None:
        folder = self._folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, "PDF 병합", "유효한 저장 폴더를 지정해 주세요.")
            return None
        name = _sanitize_filename(self._name_edit.text())
        self._name_edit.setText(name)
        target = Path(folder) / f"{name}.pdf"
        if target.exists():
            reply = QMessageBox.question(
                self,
                "PDF 병합",
                f"같은 이름의 파일이 있습니다.\n덮어쓰시겠습니까?\n\n{target}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return None
        return str(target)

    def _start_batched_merge(self, target: str, paths: list[str]) -> None:
        self._merge_token += 1
        token = self._merge_token
        self._merge_doc = PdfDocument()
        self._merge_target = target
        self._merge_insert_at = 0
        self._merge_pages = 0
        self._merge_files_done = 0
        self._merge_total_files = len(paths)

        progress = QProgressDialog(
            "파일 불러오는 중...",
            "취소",
            0,
            len(paths),
            self,
        )
        progress.setWindowTitle("PDF 병합")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.canceled.connect(lambda t=token: self._cancel_merge(t))
        self._merge_progress = progress
        self._apply_btn.setEnabled(False)

        initial = paths[:_MERGE_INITIAL_BATCH]
        remaining = paths[_MERGE_INITIAL_BATCH:]
        QTimer.singleShot(
            0,
            lambda: self._merge_next_batch(token, initial, remaining),
        )

    def _cancel_merge(self, token: int) -> None:
        if token != self._merge_token:
            return
        self._merge_token += 1
        self._cleanup_merge_ui()

    def _cleanup_merge_ui(self) -> None:
        progress = self._merge_progress
        self._merge_progress = None
        if progress is not None:
            progress.close()
        self._merge_doc = None
        self._sync_empty_state()

    def _fail_merge(self, token: int, message: str) -> None:
        if token != self._merge_token:
            return
        self._merge_token += 1
        self._cleanup_merge_ui()
        QMessageBox.critical(self, "PDF 병합 오류", message)

    def _merge_next_batch(
        self,
        token: int,
        batch: list[str],
        remaining: list[str],
    ) -> None:
        if token != self._merge_token:
            return
        progress = self._merge_progress
        if progress is not None and progress.wasCanceled():
            self._cancel_merge(token)
            return
        doc = self._merge_doc
        if doc is None or not batch:
            if remaining:
                next_batch = remaining[:_MERGE_CONTINUE_BATCH]
                rest = remaining[_MERGE_CONTINUE_BATCH:]
                QTimer.singleShot(
                    0,
                    lambda: self._merge_next_batch(token, next_batch, rest),
                )
                return
            self._finish_merge(token)
            return
        try:
            added = doc.insert_files_at(
                self._merge_insert_at,
                batch,
                record_undo=False,
                resolve_pdf_password=self._resolve_pdf_password,
            )
        except Exception as exc:
            self._fail_merge(token, str(exc))
            return
        if token != self._merge_token:
            return
        self._merge_insert_at += added
        self._merge_pages += added
        self._merge_files_done += len(batch)
        if progress is not None:
            progress.setValue(min(self._merge_files_done, self._merge_total_files))
            progress.setLabelText(
                f"파일 불러오는 중... {self._merge_pages}페이지 "
                f"({self._merge_files_done}/{self._merge_total_files})"
            )
        if remaining:
            next_batch = remaining[:_MERGE_CONTINUE_BATCH]
            rest = remaining[_MERGE_CONTINUE_BATCH:]
            QTimer.singleShot(
                0,
                lambda: self._merge_next_batch(token, next_batch, rest),
            )
            return
        self._finish_merge(token)

    def _finish_merge(self, token: int) -> None:
        if token != self._merge_token:
            return
        doc = self._merge_doc
        target = self._merge_target
        pages = self._merge_pages
        if doc is None:
            self._cleanup_merge_ui()
            return
        if pages <= 0:
            self._merge_token += 1
            self._cleanup_merge_ui()
            QMessageBox.warning(self, "PDF 병합", "병합할 페이지가 없습니다.")
            return
        try:
            doc.save(target)
        except Exception as exc:
            self._fail_merge(token, str(exc))
            return
        if token != self._merge_token:
            return
        self._settings.merge_save_folder = str(Path(target).parent)
        self._folder_edit.setText(self._settings.merge_save_folder)
        self._folder_edit.setToolTip(self._settings.merge_save_folder)
        self._output_path = target
        self._merge_token += 1
        self._cleanup_merge_ui()
        self.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_preview()

    def _apply(self) -> None:
        target = self._resolved_output_path()
        if not target:
            return
        paths = self._file_paths()
        if not paths:
            return
        self._start_batched_merge(target, paths)
