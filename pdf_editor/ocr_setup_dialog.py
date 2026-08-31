"""Explain how to install the sidecar OCR pack and choose the OCR folder."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.app_settings import AppSettings
from pdf_editor.ocr import (
    GITHUB_RELEASES_URL,
    OCR_HELPER_BIN,
    PADDLEOCR_URL,
    active_ocr_dir,
    default_ocr_dir,
    ensure_ocr_dir,
    find_ocr_helper,
    set_custom_ocr_dir,
    uses_custom_ocr_dir,
)


class OcrSetupDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OCR 팩 설치")
        self.setMinimumWidth(560)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel("OCR 팩 설치")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        root.addWidget(title)

        steps = QLabel(
            "1. 앱과 같은 릴리스 다운로드 목록에서 OCR 팩을 받습니다.\n"
            f"2. 압축을 푼 내용({OCR_HELPER_BIN}, _internal, models)을 이 OCR 폴더에 넣습니다.\n"
            "3. 이 프로그램을 다시 실행하거나 OCR 메뉴를 다시 엽니다.\n\n"
            "폴더를 따로 지정하지 않으면 기본 폴더를 사용합니다."
        )
        steps.setWordWrap(True)
        root.addWidget(steps)

        self._status = QLabel()
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        folder_label = QLabel("OCR 폴더")
        folder_label.setStyleSheet("font-weight: 600;")
        root.addWidget(folder_label)

        self._default_hint = QLabel()
        self._default_hint.setStyleSheet("color: #666666;")
        self._default_hint.setWordWrap(True)
        root.addWidget(self._default_hint)

        path_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        path_row.addWidget(self._folder_edit, 1)
        browse = QPushButton("지정...")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._choose_folder)
        path_row.addWidget(browse)
        reset = QPushButton("기본 폴더")
        reset.setAutoDefault(False)
        reset.clicked.connect(self._reset_folder)
        path_row.addWidget(reset)
        root.addLayout(path_row)

        links = QHBoxLayout()
        release_btn = QPushButton("릴리스에서 OCR 팩 받기")
        release_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        release_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_RELEASES_URL))
        )
        links.addWidget(release_btn)
        paddle_btn = QPushButton("PaddleOCR 안내")
        paddle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        paddle_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PADDLEOCR_URL)))
        links.addWidget(paddle_btn)
        links.addStretch(1)
        root.addLayout(links)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        open_btn = QPushButton("OCR 폴더 열기")
        open_btn.clicked.connect(self._open_folder)
        buttons.addWidget(open_btn)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def _refresh(self) -> None:
        folder = ensure_ocr_dir()
        self._folder_edit.setText(str(folder))
        self._folder_edit.setToolTip(str(folder))
        if uses_custom_ocr_dir():
            self._default_hint.setText(f"지정한 폴더를 사용합니다. 기본 폴더: {default_ocr_dir()}")
        else:
            self._default_hint.setText("기본 폴더를 사용합니다.")
        helper = find_ocr_helper()
        if helper is not None:
            self._status.setText(f"구성 요소를 찾았습니다.\n{helper.ocr_dir}")
            self._status.setStyleSheet("color: #2e7d32;")
        else:
            self._status.setText("아직 OCR 구성 요소가 없습니다. 아래 폴더에 넣어 주세요.")
            self._status.setStyleSheet("color: #c62828;")

    def _choose_folder(self) -> None:
        if choose_ocr_folder(self):
            self._refresh()

    def _reset_folder(self) -> None:
        set_custom_ocr_dir(None)
        self._refresh()

    def _open_folder(self) -> None:
        open_ocr_folder()


def open_ocr_folder() -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(ensure_ocr_dir())))


def choose_ocr_folder(parent: QWidget | None = None) -> bool:
    start = str(active_ocr_dir())
    folder = QFileDialog.getExistingDirectory(parent, "OCR 폴더 선택", start)
    if not folder:
        return False
    set_custom_ocr_dir(Path(folder))
    return True


def show_ocr_setup(parent: QWidget | None = None) -> None:
    OcrSetupDialog(parent).exec()
