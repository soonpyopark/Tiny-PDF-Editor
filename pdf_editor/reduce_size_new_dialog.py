"""Acrobat-style optimize dialog (용량 줄이기 신규)."""

from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)

from pdf_editor.document import (
    OPTIMIZE_DPI_CHOICES,
    OptimizeSizeOptions,
    PdfDocument,
    format_file_size,
)


class ReduceSizeNewDialog(QDialog):
    """User-defined optimize settings; progress is shown in the main viewer log."""

    def __init__(self, document: PdfDocument, parent=None) -> None:
        super().__init__(parent)
        self._document = document
        self.setWindowTitle("사용자 지정 설정")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(16, 16, 16, 12)

        header = QLabel(
            f"현재 문서 크기: {format_file_size(len(self._document.save_to_bytes()))}"
        )
        header.setStyleSheet("color: #555;")
        root.addWidget(header)

        image_group = QGroupBox("이미지 압축 해상도")
        image_layout = QFormLayout(image_group)
        self._dpi_combo = QComboBox()
        for dpi in OPTIMIZE_DPI_CHOICES:
            self._dpi_combo.addItem(f"{dpi}dpi", dpi)
        default_index = OPTIMIZE_DPI_CHOICES.index(72)
        self._dpi_combo.setCurrentIndex(default_index)
        image_layout.addRow("이미지 압축 해상도:", self._dpi_combo)
        root.addWidget(image_group)

        content_group = QGroupBox("콘텐츠 압축")
        content_layout = QVBoxLayout(content_group)
        section_font = QFont()
        section_font.setBold(True)
        content_group.setFont(section_font)

        self._dedup_check = QCheckBox("중복 리소스 제거")
        self._dedup_check.setChecked(True)
        self._stream_check = QCheckBox("스트림 콘텐츠 압축")
        self._stream_check.setChecked(True)
        self._font_check = QCheckBox("내장된 글꼴 압축")
        self._font_check.setChecked(True)
        for box in (self._dedup_check, self._stream_check, self._font_check):
            content_layout.addWidget(box)
        root.addWidget(content_group)

        delete_group = QGroupBox("삭제된 콘텐츠 압축")
        delete_layout = QVBoxLayout(delete_group)
        delete_group.setFont(section_font)

        self._bookmark_check = QCheckBox("북마크 삭제")
        self._attachment_check = QCheckBox("첨부 파일 삭제")
        self._metadata_check = QCheckBox("문서 정보 및 메타데이터 삭제")
        self._metadata_check.setChecked(True)
        self._annot_check = QCheckBox("모든 메모 및 양식 삭제")
        for box in (
            self._bookmark_check,
            self._attachment_check,
            self._metadata_check,
            self._annot_check,
        ):
            delete_layout.addWidget(box)
        root.addWidget(delete_group)

        hint = QLabel("진행 상태는 문서 하단 터미널에 표시됩니다.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("적용")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_options(self) -> OptimizeSizeOptions:
        dpi = int(self._dpi_combo.currentData())
        return OptimizeSizeOptions(
            image_dpi=dpi,
            remove_duplicate_resources=self._dedup_check.isChecked(),
            compress_streams=self._stream_check.isChecked(),
            compress_fonts=self._font_check.isChecked(),
            delete_bookmarks=self._bookmark_check.isChecked(),
            delete_attachments=self._attachment_check.isChecked(),
            delete_metadata=self._metadata_check.isChecked(),
            delete_annotations_and_forms=self._annot_check.isChecked(),
        )
