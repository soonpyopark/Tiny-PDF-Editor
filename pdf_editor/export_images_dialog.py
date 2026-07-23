"""Dialog and helpers for exporting PDF pages as image files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.document import PdfDocument

EXPORT_DPI_CHOICES = (72, 100, 150, 200, 300, 600)
_DEFAULT_DPI = 150


@dataclass(frozen=True)
class ExportImagesOptions:
    dpi: int = _DEFAULT_DPI
    image_format: str = "png"  # "png" | "jpeg"
    jpeg_quality: int = 92
    page_from: int = 1  # 1-based inclusive
    page_to: int = 1
    include_annotations: bool = True


def page_filename_width(page_count: int) -> int:
    """Zero-pad width based on total page count (e.g. 12→2, 1000→4)."""
    return max(1, len(str(max(1, page_count))))


def sanitize_export_folder_name(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    lower = base.lower()
    for ext in (".pdf", ".png", ".jpg", ".jpeg"):
        if lower.endswith(ext):
            base = base[: -len(ext)]
            break
    base = base.strip() or "문서"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).rstrip(" .")
    return cleaned or "문서"


def export_folder_name_for_document(document: PdfDocument) -> str:
    return sanitize_export_folder_name(document.display_name)


class ExportImagesDialog(QDialog):
    """Confirm export options before choosing the destination folder."""

    def __init__(self, document: PdfDocument, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document = document
        self.setWindowTitle("이미지로 저장")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self) -> None:
        page_count = max(1, self._document.page_count)
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(16, 16, 16, 12)

        summary = QLabel(
            f"총 {page_count}페이지 · 폴더명: {export_folder_name_for_document(self._document)}"
        )
        summary.setStyleSheet("color: #555;")
        summary.setWordWrap(True)
        root.addWidget(summary)

        options = QGroupBox("저장 옵션")
        form = QFormLayout(options)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._dpi_combo = QComboBox()
        for dpi in EXPORT_DPI_CHOICES:
            self._dpi_combo.addItem(f"{dpi} DPI", dpi)
        self._dpi_combo.setCurrentIndex(EXPORT_DPI_CHOICES.index(_DEFAULT_DPI))
        form.addRow("해상도:", self._dpi_combo)

        self._format_combo = QComboBox()
        self._format_combo.addItem("PNG", "png")
        self._format_combo.addItem("JPEG", "jpeg")
        self._format_combo.currentIndexChanged.connect(self._sync_quality_enabled)
        form.addRow("이미지 형식:", self._format_combo)

        self._quality_spin = QSpinBox()
        self._quality_spin.setRange(1, 100)
        self._quality_spin.setSuffix(" %")
        self._quality_spin.setValue(92)
        form.addRow("JPEG 품질:", self._quality_spin)

        range_row = QWidget()
        range_layout = QHBoxLayout(range_row)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(6)
        self._from_spin = QSpinBox()
        self._from_spin.setRange(1, page_count)
        self._from_spin.setValue(1)
        self._to_spin = QSpinBox()
        self._to_spin.setRange(1, page_count)
        self._to_spin.setValue(page_count)
        self._from_spin.valueChanged.connect(self._sync_page_range)
        self._to_spin.valueChanged.connect(self._sync_page_range)
        range_layout.addWidget(QLabel("시작"))
        range_layout.addWidget(self._from_spin)
        range_layout.addWidget(QLabel("~"))
        range_layout.addWidget(self._to_spin)
        range_layout.addWidget(QLabel("끝"))
        range_layout.addStretch(1)
        form.addRow("페이지 범위:", range_row)

        self._annots_check = QCheckBox("주석(형광펜·밑줄 등) 포함")
        self._annots_check.setChecked(True)
        form.addRow("", self._annots_check)

        pad = page_filename_width(page_count)
        hint = QLabel(
            f"파일 이름 예: {1:0{pad}d}.png … {page_count:0{pad}d}.png"
        )
        hint.setStyleSheet("color: #777; font-size: 12px;")
        form.addRow("", hint)

        root.addWidget(options)
        self._sync_quality_enabled()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("폴더 선택...")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _sync_quality_enabled(self) -> None:
        is_jpeg = self._format_combo.currentData() == "jpeg"
        self._quality_spin.setEnabled(is_jpeg)

    def _sync_page_range(self) -> None:
        if self._from_spin.value() > self._to_spin.value():
            sender = self.sender()
            if sender is self._from_spin:
                self._to_spin.setValue(self._from_spin.value())
            else:
                self._from_spin.setValue(self._to_spin.value())

    def selected_options(self) -> ExportImagesOptions:
        return ExportImagesOptions(
            dpi=int(self._dpi_combo.currentData()),
            image_format=str(self._format_combo.currentData()),
            jpeg_quality=int(self._quality_spin.value()),
            page_from=int(self._from_spin.value()),
            page_to=int(self._to_spin.value()),
            include_annotations=self._annots_check.isChecked(),
        )
