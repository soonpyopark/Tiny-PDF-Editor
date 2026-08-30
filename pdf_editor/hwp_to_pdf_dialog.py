"""Convert each HWP/HWPX file to its own PDF."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QKeyEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
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
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.app_settings import AppSettings, default_downloads_folder
from pdf_editor.hwp_convert import (
    HWP_EXTENSIONS,
    convert_hwp_to_pdf,
    hancom_installed,
)

_ACCENT = "#7eb8e8"
_ACCENT_HOVER = "#5aa3e0"
_ACCENT_PRESSED = "#3d8fd4"
_ACCENT_SOFT = "#e8f4fc"
_PATH_ROLE = Qt.ItemDataRole.UserRole
_HWP_FILTER = "한글 문서 (*.hwp *.hwpx);;모든 파일 (*.*)"


def _is_hwp_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in HWP_EXTENSIONS


def _hwp_paths_from_mime(mime: QMimeData) -> list[str]:
    paths: list[str] = []
    if not mime.hasUrls():
        return paths
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path and _is_hwp_path(path) and Path(path).is_file():
            paths.append(path)
    return paths


def _unique_pdf_path(folder: Path, stem: str) -> Path:
    candidate = folder / f"{stem}.pdf"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = folder / f"{stem} ({index}).pdf"
        if not candidate.exists():
            return candidate
        index += 1


class _HwpFileList(QListWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hwpFileList")
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self.setSpacing(2)
        self.setStyleSheet(
            """
            QListWidget#hwpFileList {
                border: 1px dashed #c8c8c8;
                border-radius: 6px;
                background: #ffffff;
                padding: 6px;
            }
            QListWidget#hwpFileList::item {
                padding: 8px 10px;
                border-radius: 4px;
            }
            QListWidget#hwpFileList::item:selected {
                background: #e8f4fc;
                color: #222222;
            }
            """
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _hwp_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _hwp_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _hwp_paths_from_mime(event.mimeData())
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        event.ignore()


class HwpToPdfDialog(QDialog):
    """Pick HWP/HWPX files and write one PDF per file."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._converted: list[str] = []
        self.setWindowTitle("한글(HWP, HWPX) → PDF")
        self.setMinimumSize(560, 480)
        self.resize(620, 520)
        self._build_ui()
        self._sync_buttons()

    def converted_paths(self) -> list[str]:
        return list(self._converted)

    def open_after_convert(self) -> bool:
        return self._open_check.isChecked()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 16)
        body_layout.setSpacing(10)

        title = QLabel("한글(HWP, HWPX) → PDF")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        body_layout.addWidget(title)

        subtitle = QLabel(
            "각 HWP/HWPX 파일을 개별 PDF로 저장합니다. Windows에서 한컴 한글이 필요합니다."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #666666;")
        body_layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self._remove_btn = QPushButton("선택 제거")
        self._remove_btn.setAutoDefault(False)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setStyleSheet(
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
        self._remove_btn.clicked.connect(self._remove_selected)
        toolbar.addWidget(self._remove_btn)

        self._folder_btn = QPushButton("폴더에서 추가")
        self._folder_btn.setAutoDefault(False)
        self._folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._folder_btn.setStyleSheet(self._remove_btn.styleSheet())
        self._folder_btn.clicked.connect(self._pick_folder_files)
        toolbar.addWidget(self._folder_btn)

        self._add_btn = QPushButton("파일 추가")
        self._add_btn.setAutoDefault(False)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet(
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
        self._add_btn.clicked.connect(self._pick_files)
        toolbar.addWidget(self._add_btn)
        body_layout.addLayout(toolbar)

        self._list = _HwpFileList()
        self._list.files_dropped.connect(self._add_paths)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        body_layout.addWidget(self._list, 1)

        hint = QLabel("한글 파일을 끌어다 놓거나 추가할 수 있습니다.")
        hint.setStyleSheet("color: #777777; font-size: 11px;")
        body_layout.addWidget(hint)

        loc_label = QLabel("저장 위치")
        loc_label.setStyleSheet("font-weight: 600; margin-top: 4px;")
        body_layout.addWidget(loc_label)

        self._beside_radio = QRadioButton("원본과 같은 폴더")
        self._folder_radio = QRadioButton("지정 폴더")
        group = QButtonGroup(self)
        group.addButton(self._beside_radio)
        group.addButton(self._folder_radio)
        if self._settings.hwp_save_beside_source:
            self._beside_radio.setChecked(True)
        else:
            self._folder_radio.setChecked(True)
        self._beside_radio.toggled.connect(self._sync_folder_enabled)
        body_layout.addWidget(self._beside_radio)
        body_layout.addWidget(self._folder_radio)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        folder = self._settings.hwp_save_folder
        if not Path(folder).is_dir():
            folder = default_downloads_folder()
            self._settings.hwp_save_folder = folder
        self._folder_edit.setText(folder)
        self._folder_edit.setToolTip(folder)
        self._browse_btn = QPushButton("...")
        self._browse_btn.setAutoDefault(False)
        self._browse_btn.setFixedWidth(36)
        self._browse_btn.clicked.connect(self._browse_folder)
        path_row.addWidget(self._folder_edit, 1)
        path_row.addWidget(self._browse_btn)
        body_layout.addLayout(path_row)

        self._overwrite_check = QCheckBox("같은 이름의 PDF가 있으면 덮어쓰기")
        body_layout.addWidget(self._overwrite_check)
        self._open_check = QCheckBox("변환 후 PDF 열기")
        body_layout.addWidget(self._open_check)

        root.addWidget(body, 1)

        footer = QFrame()
        footer.setObjectName("hwpFooter")
        footer.setStyleSheet(
            """
            QFrame#hwpFooter {
                background: #f3f3f3;
                border-top: 1px solid #e0e0e0;
            }
            """
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 10)
        footer_layout.addStretch(1)
        self._apply_btn = QPushButton("변환")
        self._apply_btn.setEnabled(False)
        self._apply_btn.setAutoDefault(True)
        self._apply_btn.setDefault(True)
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
        self._apply_btn.clicked.connect(self._convert)
        footer_layout.addWidget(self._apply_btn)
        root.addWidget(footer)
        self._sync_folder_enabled()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._apply_btn.isEnabled():
                self._convert()
                return
        super().keyPressEvent(event)

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

    def _add_paths(self, paths: list[str]) -> None:
        existing = {Path(path).resolve() for path in self._file_paths()}
        added = 0
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or not _is_hwp_path(path):
                continue
            resolved = path.resolve()
            if resolved in existing:
                continue
            item = QListWidgetItem(path.name)
            item.setToolTip(str(resolved))
            item.setData(_PATH_ROLE, str(resolved))
            self._list.addItem(item)
            existing.add(resolved)
            added += 1
        if added:
            self._sync_buttons()

    def _pick_files(self) -> None:
        start = self._folder_edit.text() or default_downloads_folder()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "한글 문서 선택", start, _HWP_FILTER
        )
        if paths:
            self._add_paths(paths)

    def _pick_folder_files(self) -> None:
        start = self._folder_edit.text() or default_downloads_folder()
        folder = QFileDialog.getExistingDirectory(self, "한글 문서가 있는 폴더 선택", start)
        if not folder:
            return
        paths = sorted(
            str(path)
            for path in Path(folder).iterdir()
            if path.is_file() and _is_hwp_path(path)
        )
        if not paths:
            QMessageBox.information(
                self,
                "한글(HWP, HWPX) → PDF",
                "선택한 폴더에 HWP/HWPX 파일이 없습니다.",
            )
            return
        self._add_paths(paths)

    def _remove_selected(self) -> None:
        for item in list(self._list.selectedItems()):
            self._list.takeItem(self._list.row(item))
        self._sync_buttons()

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
        self._folder_radio.setChecked(True)

    def _sync_folder_enabled(self) -> None:
        enabled = self._folder_radio.isChecked()
        self._folder_edit.setEnabled(enabled)
        self._browse_btn.setEnabled(enabled)

    def _sync_buttons(self) -> None:
        has_files = self._list.count() > 0
        self._apply_btn.setEnabled(has_files)
        self._remove_btn.setEnabled(bool(self._list.selectedItems()))

    def _destination_for(self, source: Path) -> Path:
        folder = (
            source.parent
            if self._beside_radio.isChecked()
            else Path(self._folder_edit.text())
        )
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{source.stem}.pdf"
        if dest.exists() and not self._overwrite_check.isChecked():
            return _unique_pdf_path(folder, source.stem)
        return dest

    def _persist_settings(self) -> None:
        self._settings.hwp_save_beside_source = self._beside_radio.isChecked()
        folder = self._folder_edit.text().strip()
        if folder and Path(folder).is_dir():
            self._settings.hwp_save_folder = folder
        self._settings.save()

    def _convert(self) -> None:
        if sys.platform != "win32":
            QMessageBox.information(
                self,
                "한글(HWP, HWPX) → PDF",
                "HWP/HWPX 변환은 Windows에서만 지원됩니다.",
            )
            return
        if not hancom_installed():
            QMessageBox.warning(
                self,
                "한글(HWP, HWPX) → PDF",
                "한컴 한글(한컴오피스)이 설치되어 있지 않습니다.\n\n"
                "HWP/HWPX 파일을 PDF로 변환하려면 한컴 한글이 필요합니다.",
            )
            return
        paths = [Path(path) for path in self._file_paths()]
        if not paths:
            return
        if self._folder_radio.isChecked() and not Path(self._folder_edit.text()).is_dir():
            QMessageBox.warning(self, "한글(HWP, HWPX) → PDF", "유효한 저장 폴더를 지정해 주세요.")
            return

        progress = QProgressDialog("", "중지", 0, len(paths), self)
        progress.setWindowTitle("한글(HWP, HWPX) → PDF")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(360)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()

        converted: list[str] = []
        failed: list[tuple[str, str]] = []
        for index, source in enumerate(paths, start=1):
            if progress.wasCanceled():
                break
            progress.setLabelText(f"{index}/{len(paths)} 변환 중…\n{source.name}")
            QApplication.processEvents()
            try:
                dest = self._destination_for(source)
                convert_hwp_to_pdf(source, dest)
                converted.append(str(dest))
            except Exception as exc:
                failed.append((source.name, str(exc)))
            progress.setValue(index)
            QApplication.processEvents()
        progress.close()

        self._persist_settings()
        self._converted = converted

        if not converted and not failed:
            return

        if converted and not failed:
            QMessageBox.information(
                self,
                "한글(HWP, HWPX) → PDF",
                f"{len(converted)}개 파일을 PDF로 변환했습니다.",
            )
            self.accept()
            return

        details = "\n".join(f"• {name}: {message}" for name, message in failed)
        if converted:
            QMessageBox.warning(
                self,
                "한글(HWP, HWPX) → PDF",
                f"{len(converted)}개 변환, {len(failed)}개 실패.\n\n{details}",
            )
            self.accept()
            return
        QMessageBox.critical(self, "한글(HWP, HWPX) → PDF", f"변환에 실패했습니다.\n\n{details}")
