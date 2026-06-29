"""Dialog for PDF size reduction (optimize)."""

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
    QSpinBox,
    QVBoxLayout,
)

from pdf_editor.document import (
    OPTIMIZE_DPI_CHOICES,
    OptimizeSizeOptions,
    PdfDocument,
    format_file_size,
)

_PERCENT_SPIN_WIDTH = 96


def _make_percent_spinbox() -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(1, 100)
    spin.setSuffix(" %")
    spin.setFixedWidth(_PERCENT_SPIN_WIDTH)
    return spin


class ReduceSizeDialog(QDialog):
    """User-defined optimize settings; progress is shown in the main viewer log."""

    def __init__(self, document: PdfDocument, parent=None) -> None:
        super().__init__(parent)
        self._document = document
        self.setWindowTitle("용량 줄이기")
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

        image_group = QGroupBox("이미지 설정 조정")
        image_layout = QFormLayout(image_group)
        image_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )
        section_font = QFont()
        section_font.setBold(True)
        image_group.setFont(section_font)

        self._dpi_combo = QComboBox()
        for dpi in OPTIMIZE_DPI_CHOICES:
            self._dpi_combo.addItem(f"{dpi}dpi", dpi)
        default_index = OPTIMIZE_DPI_CHOICES.index(72)
        self._dpi_combo.setCurrentIndex(default_index)
        self._dpi_combo.setFixedWidth(_PERCENT_SPIN_WIDTH)
        image_layout.addRow("이미지 압축 해상도:", self._dpi_combo)

        self._quality_spin = _make_percent_spinbox()
        self._quality_spin.setValue(100)
        image_layout.addRow("이미지 품질:", self._quality_spin)

        self._size_spin = _make_percent_spinbox()
        self._size_spin.setValue(100)
        image_layout.addRow("이미지 사이즈:", self._size_spin)

        image_hint = QLabel(
            "압축 해상도만으로 원하는 용량에 도달하지 못할 때 "
            "품질·사이즈를 낮춰 추가로 줄일 수 있습니다."
        )
        image_hint.setWordWrap(True)
        image_hint.setStyleSheet("color: #666; font-size: 11px;")
        image_layout.addRow(image_hint)
        root.addWidget(image_group)

        content_group = QGroupBox("콘텐츠 압축")
        content_layout = QVBoxLayout(content_group)
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
            image_quality_percent=self._quality_spin.value(),
            image_size_percent=self._size_spin.value(),
            remove_duplicate_resources=self._dedup_check.isChecked(),
            compress_streams=self._stream_check.isChecked(),
            compress_fonts=self._font_check.isChecked(),
        )
