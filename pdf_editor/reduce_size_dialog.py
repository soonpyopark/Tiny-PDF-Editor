"""Dialog for PDF size reduction with estimation."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.document import (
    PRESET_OPTIONS,
    PdfDocument,
    ReduceSizeOptions,
    format_file_size,
)

_ADVANCED_LABEL_WIDTH = 108
_ADVANCED_RIGHT_WIDTH = 96
_STEP_HEADER_FONT = QFont("", 9, QFont.Weight.DemiBold)
_PANEL_FRAME_STYLE = (
    "QFrame { background: #fafafa; border: 1px solid #e4e4e4; border-radius: 8px; }"
)
_DIALOG_WIDTH = 800
_SETTINGS_HEADER_HEIGHT = 44
_STEP1_BTN_RELOCATE_SAVED_HEIGHT = 14  # root spacing removed when btn joins step1 section
_EXTRA_TERMINAL_HEIGHT = 48
_PROGRESS_LOG_MIN_HEIGHT = (
    110 + _SETTINGS_HEADER_HEIGHT + _STEP1_BTN_RELOCATE_SAVED_HEIGHT + _EXTRA_TERMINAL_HEIGHT
)
_PROGRESS_LOG_MAX_HEIGHT = (
    150 + _SETTINGS_HEADER_HEIGHT + _STEP1_BTN_RELOCATE_SAVED_HEIGHT + _EXTRA_TERMINAL_HEIGHT
)
_PRIMARY_BTN_STYLE = """
    QPushButton {
        background: #1a73e8;
        color: white;
        font-weight: 600;
        font-size: 13px;
        border: none;
        border-radius: 8px;
        padding: 10px 14px;
    }
    QPushButton:hover { background: #1558b0; }
    QPushButton:disabled { background: #a8c7f5; }
"""
_MIN_DPI = 24
_MAX_DPI = 300
_MIN_QUALITY = 1
_MAX_QUALITY = 95
_DEFAULT_PRESET = "balanced"
_IMAGE_PROGRESS_PREFIX = "  이미지 조정 중... "
_DESIRED_MB_MIN = 4.5
_DESIRED_MB_MAX = 10.0
_DESIRED_MB_STEP = 0.1
_DESIRED_MB_DEFAULT = 9.8
_DESIRED_SLIDER_STEPS = int(
    (_DESIRED_MB_MAX - _DESIRED_MB_MIN) / _DESIRED_MB_STEP
)
_MAX_TARGET_FIT_PASSES = 15
_TARGET_UNDERSHOOT = 0.96
_ESTIMATE_REQUIRED_MESSAGE = (
    "먼저 [예상 최종 크기 산정]을 실행해 주세요."
)


def _make_step_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(_STEP_HEADER_FONT)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return label


def _make_advanced_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFixedWidth(_ADVANCED_LABEL_WIDTH)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    label.setWordWrap(False)
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return label


def _make_percent_spinbox(minimum: int, maximum: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(" %")
    spin.setFixedWidth(_ADVANCED_RIGHT_WIDTH)
    return spin


def _mb_to_slider(mb: float) -> int:
    return int(round((mb - _DESIRED_MB_MIN) / _DESIRED_MB_STEP))


def _slider_to_mb(index: int) -> float:
    return round(_DESIRED_MB_MIN + index * _DESIRED_MB_STEP, 1)


def _is_below_target(size: int, target_bytes: int) -> bool:
    return size > 0 and size < target_bytes


def _is_close_enough_below(size: int, target_bytes: int) -> bool:
    """True when *size* is below but within one undershoot step of *target_bytes*."""
    return _is_below_target(size, target_bytes) and size >= int(target_bytes * _TARGET_UNDERSHOOT)


def _coerce_payload_bytes(payload: object) -> bytes | None:
    """Normalize worker payload to bytes (PyQt may deliver QByteArray across threads)."""
    if payload is None:
        return None
    if isinstance(payload, bytes):
        data = payload
    elif isinstance(payload, bytearray):
        data = bytes(payload)
    else:
        try:
            data = bytes(payload)
        except TypeError:
            return None
    return data if data else None


class _EstimateWorker(QThread):
    progress = pyqtSignal(str)
    page_progress = pyqtSignal(int, int)
    image_progress = pyqtSignal(int, int)
    finished = pyqtSignal(int, object)

    def __init__(
        self,
        source_bytes: bytes,
        options: ReduceSizeOptions,
    ) -> None:
        super().__init__()
        self._source_bytes = source_bytes
        self._options = options

    def run(self) -> None:
        reduced = None
        try:
            def on_status(message: str) -> None:
                self.progress.emit(message)

            def on_page(current: int, total: int) -> None:
                self.page_progress.emit(current, total)

            def on_image(current: int, total: int) -> None:
                self.image_progress.emit(current, total)

            self.progress.emit("> 예상 최종 크기 산정을 시작합니다...")
            reduced = PdfDocument.compress_document_bytes(
                self._source_bytes,
                self._options,
                page_progress=on_page,
                status_callback=on_status,
                image_progress=on_image,
            )
            self.progress.emit("압축된 문서 크기를 계산하는 중...")
            payload = PdfDocument._serialize_doc_bytes(reduced)
            size = len(payload)
            self.progress.emit(f"완료: 예상 최종 크기 {format_file_size(size)}")
            self.finished.emit(size, payload)
        except Exception as exc:
            self.progress.emit(f"오류: {exc}")
            self.finished.emit(-1, b"")
        finally:
            if reduced is not None:
                reduced.close()


class ReduceSizeDialog(QDialog):
    """Modal dialog to configure and apply PDF size reduction."""

    def __init__(self, document: PdfDocument, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document = document
        self._original_size = document.current_file_size()
        self._active_preset = _DEFAULT_PRESET
        self._worker: _EstimateWorker | None = None
        self._estimated_size_bytes: int | None = None
        self._last_reduced_payload: bytes | None = None
        self._pending_target_bytes: int | None = None
        self._pending_target_label: str = ""
        self._target_fit_pass = 0
        self._target_fit_mode: str | None = None
        self._best_below_size: int | None = None
        self._best_below_payload: bytes | None = None
        self._target_color_user_declined = False
        self._final_apply_ready = False
        self.result_before = self._original_size
        self.result_after = self._original_size

        self.setWindowTitle("용량 줄이기")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        self._advanced_panel = QFrame()
        self._advanced_panel.setStyleSheet(_PANEL_FRAME_STYLE)
        advanced_layout = QVBoxLayout(self._advanced_panel)
        advanced_layout.setContentsMargins(14, 12, 14, 12)
        advanced_layout.setSpacing(12)

        advanced_grid = QGridLayout()
        advanced_grid.setHorizontalSpacing(10)
        advanced_grid.setVerticalSpacing(12)
        advanced_grid.setColumnStretch(1, 1)

        size_label = _make_advanced_label("이미지 사이즈")
        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(1, 100)
        self._size_slider.valueChanged.connect(self._on_size_slider_changed)
        self._size_spin = _make_percent_spinbox(1, 100)
        self._size_spin.valueChanged.connect(self._on_size_spin_changed)

        quality_label = _make_advanced_label("이미지 품질")
        self._quality_slider = QSlider(Qt.Orientation.Horizontal)
        self._quality_slider.setRange(_MIN_QUALITY, _MAX_QUALITY)
        self._quality_slider.valueChanged.connect(self._on_quality_slider_changed)
        self._quality_spin = _make_percent_spinbox(_MIN_QUALITY, _MAX_QUALITY)
        self._quality_spin.valueChanged.connect(self._on_quality_spin_changed)

        dpi_label = _make_advanced_label("최대 DPI 제한")
        self._dpi_slider = QSlider(Qt.Orientation.Horizontal)
        self._dpi_slider.setRange(_MIN_DPI, _MAX_DPI)
        self._dpi_slider.valueChanged.connect(self._on_dpi_slider_changed)
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(_MIN_DPI, _MAX_DPI)
        self._dpi_spin.setSuffix(" DPI")
        self._dpi_spin.setFixedWidth(_ADVANCED_RIGHT_WIDTH)
        self._dpi_spin.valueChanged.connect(self._on_dpi_spin_changed)

        advanced_grid.addWidget(size_label, 0, 0)
        advanced_grid.addWidget(self._size_slider, 0, 1)
        advanced_grid.addWidget(self._size_spin, 0, 2)
        advanced_grid.addWidget(quality_label, 1, 0)
        advanced_grid.addWidget(self._quality_slider, 1, 1)
        advanced_grid.addWidget(self._quality_spin, 1, 2)
        advanced_grid.addWidget(dpi_label, 2, 0)
        advanced_grid.addWidget(self._dpi_slider, 2, 1)
        advanced_grid.addWidget(self._dpi_spin, 2, 2)

        control_row_height = self._size_spin.sizeHint().height()
        for label in (size_label, quality_label, dpi_label):
            label.setFixedHeight(control_row_height)

        color_row = QHBoxLayout()
        color_row.setSpacing(16)
        self._grayscale_check = QCheckBox("회색조로 변환 (Grayscale)")
        self._grayscale_check.toggled.connect(self._on_grayscale_toggled)
        self._monochrome_check = QCheckBox("단색조로 변환 (Monochrome)")
        self._monochrome_check.toggled.connect(self._on_monochrome_toggled)
        color_row.addWidget(self._grayscale_check)
        color_row.addWidget(self._monochrome_check)
        color_row.addStretch(1)

        advanced_layout.addLayout(advanced_grid)
        advanced_layout.addLayout(color_row)

        step1_section = QWidget()
        step1_section_layout = QVBoxLayout(step1_section)
        step1_section_layout.setContentsMargins(0, 0, 0, 0)
        step1_section_layout.setSpacing(10)
        step1_section_layout.addWidget(_make_step_label("[1단계] 예상 최종 크기 산정"))
        step1_section_layout.addWidget(self._advanced_panel)

        outline_btn_style = """
            QPushButton {
                background: #ffffff;
                color: #1a73e8;
                font-weight: 600;
                font-size: 13px;
                border: 1px solid #1a73e8;
                border-radius: 8px;
                padding: 10px 14px;
            }
            QPushButton:hover { background: #eef4ff; }
            QPushButton:disabled { color: #a8c7f5; border-color: #a8c7f5; }
            """

        step1_row = QWidget()
        step1_layout = QHBoxLayout(step1_row)
        step1_layout.setContentsMargins(0, 0, 0, 0)
        step1_layout.setSpacing(10)

        self._estimate_btn = QPushButton("예상 최종 크기 산정")
        self._estimate_btn.setMinimumHeight(40)
        self._estimate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._estimate_btn.setStyleSheet(outline_btn_style)
        self._estimate_btn.clicked.connect(self._run_step1_estimate)
        step1_layout.addWidget(self._estimate_btn)
        step1_layout.addStretch(1)
        self._original_size_label = QLabel(f"원본 크기: {format_file_size(self._original_size)}")
        self._original_size_label.setStyleSheet("font-size: 12px; color: #555555; border: none;")
        self._estimated_size_label = QLabel("예상 최종 크기: -")
        self._estimated_size_label.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #1a73e8; border: none;"
        )
        step1_layout.addWidget(self._original_size_label)
        step1_layout.addSpacing(12)
        step1_layout.addWidget(self._estimated_size_label)
        step1_section_layout.addWidget(step1_row)
        root.addWidget(step1_section)

        step2_section = QWidget()
        step2_layout = QVBoxLayout(step2_section)
        step2_layout.setContentsMargins(0, 0, 0, 0)
        step2_layout.setSpacing(10)

        step2_layout.addWidget(
            _make_step_label("[2단계] (선택) 희망 최종 용량 설정 및 용량 줄이기 자동 반복")
        )

        desired_panel = QFrame()
        desired_panel.setStyleSheet(_PANEL_FRAME_STYLE)
        desired_grid = QGridLayout(desired_panel)
        desired_grid.setContentsMargins(14, 6, 14, 6)
        desired_grid.setHorizontalSpacing(10)
        desired_grid.setColumnStretch(1, 1)

        desired_label = _make_advanced_label("희망 최종 용량")
        desired_label.setFixedHeight(control_row_height)

        self._desired_slider = QSlider(Qt.Orientation.Horizontal)
        self._desired_slider.setRange(0, _DESIRED_SLIDER_STEPS)
        self._desired_slider.setValue(_mb_to_slider(_DESIRED_MB_DEFAULT))
        self._desired_slider.valueChanged.connect(self._on_desired_slider_changed)

        self._desired_spin = QDoubleSpinBox()
        self._desired_spin.setRange(_DESIRED_MB_MIN, _DESIRED_MB_MAX)
        self._desired_spin.setSingleStep(_DESIRED_MB_STEP)
        self._desired_spin.setDecimals(1)
        self._desired_spin.setSuffix(" MB")
        self._desired_spin.setFixedWidth(_ADVANCED_RIGHT_WIDTH + 16)
        self._desired_spin.setValue(_DESIRED_MB_DEFAULT)
        self._desired_spin.valueChanged.connect(self._on_desired_spin_changed)

        desired_grid.addWidget(desired_label, 0, 0)
        desired_grid.addWidget(self._desired_slider, 0, 1)
        desired_grid.addWidget(self._desired_spin, 0, 2)

        self._apply_btn = QPushButton("용량 줄이기 반복 실행")
        self._apply_btn.setMinimumHeight(40)
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._apply_btn.clicked.connect(self._apply_reduction)

        step2_layout.addWidget(desired_panel)
        apply_row = QHBoxLayout()
        apply_row.setContentsMargins(0, 0, 0, 0)
        apply_row.addWidget(self._apply_btn)
        apply_row.addStretch(1)
        step2_layout.addLayout(apply_row)
        root.addWidget(step2_section)

        self._progress_log = QPlainTextEdit()
        self._progress_log.setReadOnly(True)
        self._progress_log.setPlaceholderText("작업 진행 상태가 여기에 표시됩니다.")
        self._progress_log.setMinimumHeight(_PROGRESS_LOG_MIN_HEIGHT)
        self._progress_log.setMaximumHeight(_PROGRESS_LOG_MAX_HEIGHT)
        self._progress_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._progress_log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._progress_log.setStyleSheet(
            """
            QPlainTextEdit {
                background: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 6px;
            }
            """
        )
        root.addWidget(self._progress_log)

        self._final_apply_btn = QPushButton("최종 적용 하기")
        self._final_apply_btn.setMinimumHeight(40)
        self._final_apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._final_apply_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._final_apply_btn.setEnabled(False)
        self._final_apply_btn.clicked.connect(self._confirm_final_apply)
        final_apply_row = QHBoxLayout()
        final_apply_row.setContentsMargins(0, 0, 0, 0)
        final_apply_row.addWidget(self._final_apply_btn)
        final_apply_row.addStretch(1)
        root.addLayout(final_apply_row)

        action_btn_width = max(
            self._estimate_btn.sizeHint().width(),
            self._apply_btn.sizeHint().width(),
            self._final_apply_btn.sizeHint().width(),
        )
        self._estimate_btn.setFixedWidth(action_btn_width)
        self._apply_btn.setFixedWidth(action_btn_width)
        self._final_apply_btn.setFixedWidth(action_btn_width)

        self._apply_default_options()
        self._fit_dialog_size()

    def _fit_dialog_size(self) -> None:
        """Keep dialog width fixed; adjust height only when content changes."""
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        margins = layout.contentsMargins()
        height = layout.sizeHint().height() + margins.top() + margins.bottom()
        self.setFixedSize(_DIALOG_WIDTH, height)

    def _invalidate_estimate(self) -> None:
        self._estimated_size_bytes = None
        self._last_reduced_payload = None
        self._final_apply_ready = False
        self._estimated_size_label.setText("예상 최종 크기: -")
        self._update_final_apply_btn()

    def _has_valid_estimate(self) -> bool:
        return self._estimated_size_bytes is not None and self._estimated_size_bytes >= 0

    def _warn_estimate_required(self) -> None:
        QMessageBox.warning(self, "용량 줄이기", _ESTIMATE_REQUIRED_MESSAGE)

    def _desired_target_bytes(self) -> int:
        return int(self._desired_spin.value() * 1024 * 1024)

    def _desired_target_label(self) -> str:
        return f"희망 최종 용량 {self._desired_spin.value():.1f}MB"

    def _on_desired_slider_changed(self, value: int) -> None:
        mb = _slider_to_mb(value)
        self._desired_spin.blockSignals(True)
        self._desired_spin.setValue(mb)
        self._desired_spin.blockSignals(False)

    def _on_desired_spin_changed(self, value: float) -> None:
        snapped = round(
            max(_DESIRED_MB_MIN, min(_DESIRED_MB_MAX, value)) / _DESIRED_MB_STEP
        ) * _DESIRED_MB_STEP
        if abs(snapped - value) > 1e-6:
            self._desired_spin.blockSignals(True)
            self._desired_spin.setValue(snapped)
            self._desired_spin.blockSignals(False)
            value = snapped
        self._desired_slider.blockSignals(True)
        self._desired_slider.setValue(_mb_to_slider(value))
        self._desired_slider.blockSignals(False)

    def _apply_default_options(self) -> None:
        options = PRESET_OPTIONS[_DEFAULT_PRESET]
        self._active_preset = _DEFAULT_PRESET
        self._block_advanced_signals(True)
        self._size_slider.setValue(options.image_size_percent)
        self._size_spin.setValue(options.image_size_percent)
        self._quality_slider.setValue(options.jpeg_quality)
        self._quality_spin.setValue(options.jpeg_quality)
        self._dpi_slider.setValue(options.max_dpi)
        self._dpi_spin.setValue(options.max_dpi)
        self._grayscale_check.setChecked(options.grayscale)
        self._monochrome_check.setChecked(options.monochrome)
        self._block_advanced_signals(False)

    def _block_advanced_signals(self, block: bool) -> None:
        for widget in (
            self._size_slider,
            self._size_spin,
            self._quality_slider,
            self._quality_spin,
            self._dpi_slider,
            self._dpi_spin,
            self._grayscale_check,
            self._monochrome_check,
        ):
            widget.blockSignals(block)

    def _on_grayscale_toggled(self, checked: bool) -> None:
        if checked and self._monochrome_check.isChecked():
            self._monochrome_check.blockSignals(True)
            self._monochrome_check.setChecked(False)
            self._monochrome_check.blockSignals(False)
        self._on_advanced_changed()

    def _on_monochrome_toggled(self, checked: bool) -> None:
        if checked and self._grayscale_check.isChecked():
            self._grayscale_check.blockSignals(True)
            self._grayscale_check.setChecked(False)
            self._grayscale_check.blockSignals(False)
        self._on_advanced_changed()

    def _on_size_slider_changed(self, value: int) -> None:
        self._size_spin.blockSignals(True)
        self._size_spin.setValue(value)
        self._size_spin.blockSignals(False)
        self._on_advanced_changed()

    def _on_size_spin_changed(self, value: int) -> None:
        self._size_slider.blockSignals(True)
        self._size_slider.setValue(value)
        self._size_slider.blockSignals(False)
        self._on_advanced_changed()

    def _on_quality_slider_changed(self, value: int) -> None:
        self._quality_spin.blockSignals(True)
        self._quality_spin.setValue(value)
        self._quality_spin.blockSignals(False)
        self._on_advanced_changed()

    def _on_quality_spin_changed(self, value: int) -> None:
        self._quality_slider.blockSignals(True)
        self._quality_slider.setValue(value)
        self._quality_slider.blockSignals(False)
        self._on_advanced_changed()

    def _on_dpi_slider_changed(self, value: int) -> None:
        self._dpi_spin.blockSignals(True)
        self._dpi_spin.setValue(value)
        self._dpi_spin.blockSignals(False)
        self._on_advanced_changed()

    def _on_dpi_spin_changed(self, value: int) -> None:
        self._dpi_slider.blockSignals(True)
        self._dpi_slider.setValue(value)
        self._dpi_slider.blockSignals(False)
        self._on_advanced_changed()

    def _on_advanced_changed(self) -> None:
        self._active_preset = "custom"
        self._invalidate_estimate()

    def _current_options(self) -> ReduceSizeOptions:
        return ReduceSizeOptions(
            preset=self._active_preset,
            jpeg_quality=self._quality_slider.value(),
            max_dpi=self._dpi_spin.value(),
            image_size_percent=self._size_slider.value(),
            grayscale=self._grayscale_check.isChecked(),
            monochrome=self._monochrome_check.isChecked(),
        )

    def _is_worker_busy(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def _set_advanced_values(
        self,
        *,
        image_size_percent: int,
        jpeg_quality: int,
        max_dpi: int,
        grayscale: bool | None = None,
        monochrome: bool | None = None,
    ) -> None:
        self._block_advanced_signals(True)
        self._size_slider.setValue(image_size_percent)
        self._size_spin.setValue(image_size_percent)
        self._quality_slider.setValue(jpeg_quality)
        self._quality_spin.setValue(jpeg_quality)
        self._dpi_slider.setValue(max_dpi)
        self._dpi_spin.setValue(max_dpi)
        if grayscale is not None:
            self._grayscale_check.setChecked(grayscale)
        if monochrome is not None:
            self._monochrome_check.setChecked(monochrome)
        self._block_advanced_signals(False)
        self._active_preset = "custom"

    def _remember_best_below(self, size: int) -> None:
        if self._last_reduced_payload is None:
            return
        if self._best_below_size is None or size > self._best_below_size:
            self._best_below_size = size
            self._best_below_payload = self._last_reduced_payload

    def _apply_best_below_snapshot(self) -> None:
        if self._best_below_size is None:
            return
        self._estimated_size_bytes = self._best_below_size
        self._last_reduced_payload = self._best_below_payload
        self._estimated_size_label.setText(
            f"예상 최종 크기: {format_file_size(self._best_below_size)}"
        )

    def _adjust_settings_down_to_target(self, target_bytes: int, label: str) -> bool:
        """Lower image size, quality, and DPI when the estimate is above *target_bytes*."""
        current = self._estimated_size_bytes
        if current is None or current <= 0:
            return False

        if _is_below_target(current, target_bytes):
            return False

        size = self._size_slider.value()
        quality = self._quality_slider.value()
        dpi = self._dpi_spin.value()

        ratio = (target_bytes / current) * _TARGET_UNDERSHOOT
        factor = ratio ** 0.35
        new_size = max(1, min(100, round(size * factor)))
        new_quality = max(_MIN_QUALITY, min(_MAX_QUALITY, round(quality * factor)))
        new_dpi = max(_MIN_DPI, min(_MAX_DPI, round(dpi * factor)))

        if ratio < 1.0:
            if new_size == size and size > 1:
                new_size = size - 1
            if new_quality == quality and quality > _MIN_QUALITY:
                new_quality = quality - 1
            if new_dpi == dpi and dpi > _MIN_DPI:
                new_dpi = dpi - 1

        if new_size == size and new_quality == quality and new_dpi == dpi:
            self._append_progress(
                f"  이미지 사이즈·품질·DPI를 더 낮출 수 없습니다 "
                f"({format_file_size(current)})."
            )
            return False

        self._set_advanced_values(
            image_size_percent=new_size,
            jpeg_quality=new_quality,
            max_dpi=new_dpi,
        )
        self._append_progress(
            f"  설정 조정 ({self._target_fit_pass + 1}차): "
            f"이미지 사이즈 {size}% → {new_size}%, "
            f"품질 {quality}% → {new_quality}%, DPI {dpi} → {new_dpi}"
        )
        return True

    def _adjust_settings_up_to_target(self, target_bytes: int, label: str) -> bool:
        """Raise image size, quality, and DPI when the estimate is below *target_bytes*."""
        current = self._estimated_size_bytes
        if current is None or current <= 0:
            return False

        if not _is_below_target(current, target_bytes):
            return False

        if _is_close_enough_below(current, target_bytes):
            return False

        size = self._size_slider.value()
        quality = self._quality_slider.value()
        dpi = self._dpi_spin.value()

        ratio = (target_bytes / current) * _TARGET_UNDERSHOOT
        factor = ratio ** 0.35
        new_size = max(1, min(100, round(size * factor)))
        new_quality = max(_MIN_QUALITY, min(_MAX_QUALITY, round(quality * factor)))
        new_dpi = max(_MIN_DPI, min(_MAX_DPI, round(dpi * factor)))

        if ratio > 1.0:
            if new_size == size and size < 100:
                new_size = size + 1
            if new_quality == quality and quality < _MAX_QUALITY:
                new_quality = quality + 1
            if new_dpi == dpi and dpi < _MAX_DPI:
                new_dpi = dpi + 1

        if new_size == size and new_quality == quality and new_dpi == dpi:
            self._append_progress(
                f"  이미지 사이즈·품질·DPI를 더 높일 수 없습니다 "
                f"({format_file_size(current)})."
            )
            return False

        self._set_advanced_values(
            image_size_percent=new_size,
            jpeg_quality=new_quality,
            max_dpi=new_dpi,
        )
        self._append_progress(
            f"  설정 상향 ({self._target_fit_pass + 1}차): "
            f"이미지 사이즈 {size}% → {new_size}%, "
            f"품질 {quality}% → {new_quality}%, DPI {dpi} → {new_dpi}"
        )
        return True

    def _prompt_color_mode_for_target(self) -> str | None:
        """Ask whether to apply grayscale or monochrome; None if declined or unnecessary."""
        if self._target_color_user_declined:
            return None

        grayscale = self._grayscale_check.isChecked()
        monochrome = self._monochrome_check.isChecked()
        if monochrome:
            return None

        target = self._pending_target_bytes
        label = self._pending_target_label
        current = self._estimated_size_bytes
        if target is None or current is None:
            return None

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("용량 줄이기")
        box.setWindowModality(Qt.WindowModality.ApplicationModal)
        box.setText(
            f"현재 예상 크기는 {format_file_size(current)}입니다.\n"
            f"{label}에 도달하려면 이미지 설정만으로는 어려울 수 있습니다."
        )
        box.setInformativeText("회색조 또는 단색조 변환을 적용할까요?")

        if grayscale:
            mono_btn = box.addButton(
                "단색조로 변환 (Monochrome)",
                QMessageBox.ButtonRole.AcceptRole,
            )
            box.addButton("적용 안 함", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is mono_btn:
                return "monochrome"
            self._target_color_user_declined = True
            return None

        gray_btn = box.addButton(
            "회색조로 변환 (Grayscale)",
            QMessageBox.ButtonRole.AcceptRole,
        )
        mono_btn = box.addButton(
            "단색조로 변환 (Monochrome)",
            QMessageBox.ButtonRole.AcceptRole,
        )
        box.addButton("적용 안 함", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is gray_btn:
            return "grayscale"
        if clicked is mono_btn:
            return "monochrome"
        self._target_color_user_declined = True
        return None

    def _try_color_mode_for_target(self, size: int) -> bool:
        """Offer color conversion and re-estimate; return True if a new estimate started."""
        target = self._pending_target_bytes
        if target is None or size < 0:
            return False
        if _is_below_target(size, target):
            return False

        choice = self._prompt_color_mode_for_target()
        if choice is None:
            return False

        cur_size = self._size_slider.value()
        quality = self._quality_slider.value()
        dpi = self._dpi_spin.value()
        if choice == "grayscale":
            self._append_progress("  사용자 선택: 회색조 변환을 적용합니다.")
            self._set_advanced_values(
                image_size_percent=cur_size,
                jpeg_quality=quality,
                max_dpi=dpi,
                grayscale=True,
                monochrome=False,
            )
        else:
            self._append_progress("  사용자 선택: 단색조 변환을 적용합니다.")
            self._set_advanced_values(
                image_size_percent=cur_size,
                jpeg_quality=quality,
                max_dpi=dpi,
                grayscale=False,
                monochrome=True,
            )

        self._target_fit_pass = 0
        self._estimated_size_bytes = None
        self._estimated_size_label.setText("예상 최종 크기: 재산정 중...")
        self._schedule_estimate(keep_log=True)
        return True

    def _try_finish_or_offer_color_mode(self, size: int) -> bool:
        """Finish target fit, or offer color mode first. True if re-estimate started."""
        target = self._pending_target_bytes
        if target is None:
            self._finish_target_fit(size)
            return False

        if _is_below_target(size, target):
            self._finish_target_fit(size)
            return False

        if self._try_color_mode_for_target(size):
            return True

        self._finish_target_fit(size)
        return False

    def _finish_target_fit(self, size: int) -> None:
        target = self._pending_target_bytes
        label = self._pending_target_label
        self._pending_target_bytes = None
        self._pending_target_label = ""
        self._target_fit_pass = 0
        self._target_fit_mode = None
        self._best_below_size = None
        self._best_below_payload = None

        if target is None:
            return
        if size < 0:
            self._final_apply_ready = False
            self._set_controls_enabled(True)
            return

        if _is_below_target(size, target):
            self._final_apply_ready = True
            self._append_progress(
                f"완료: {label} 목표({format_file_size(target)}) 미만입니다 "
                f"({format_file_size(size)}). "
                "[최종 적용 하기]를 눌러 문서에 적용하세요."
            )
        elif self._has_valid_estimate() and self._last_reduced_payload is not None:
            self._final_apply_ready = True
            self._append_progress(
                f"참고: 예상 크기 {format_file_size(size)}로 "
                f"{label} 목표({format_file_size(target)}) 미만에 도달하지 못했습니다. "
                "현재 설정으로 [최종 적용 하기]를 사용할 수 있습니다."
            )
        else:
            self._final_apply_ready = False
            self._append_progress(
                f"참고: 예상 크기 {format_file_size(size)}로 "
                f"{label} 목표({format_file_size(target)}) 미만에 도달하지 못했습니다."
            )

        self._set_controls_enabled(True)
        self._update_final_apply_btn()

    def _continue_target_fit_if_needed(self, size: int) -> bool:
        """Return True if another estimate pass was started."""
        target = self._pending_target_bytes
        if target is None or size < 0:
            return False

        if self._target_fit_mode == "up":
            if _is_below_target(size, target):
                self._remember_best_below(size)
                if _is_close_enough_below(size, target):
                    self._finish_target_fit(size)
                    return False

                if self._target_fit_pass >= _MAX_TARGET_FIT_PASSES:
                    self._apply_best_below_snapshot()
                    self._finish_target_fit(self._best_below_size or size)
                    return False

                if not self._adjust_settings_up_to_target(target, self._pending_target_label):
                    if self._best_below_size is not None:
                        self._apply_best_below_snapshot()
                        self._finish_target_fit(self._best_below_size)
                    else:
                        self._finish_target_fit(size)
                    return False

                self._target_fit_pass += 1
                self._estimated_size_bytes = None
                self._estimated_size_label.setText("예상 최종 크기: 재산정 중...")
                self._schedule_estimate(keep_log=True)
                return True

            if self._best_below_size is not None:
                self._apply_best_below_snapshot()
                self._finish_target_fit(self._best_below_size)
                return False

            self._append_progress("  목표 용량을 초과했습니다. 설정을 낮춥니다...")
            self._target_fit_mode = "down"

        if _is_below_target(size, target):
            self._finish_target_fit(size)
            return False

        if self._target_fit_pass >= _MAX_TARGET_FIT_PASSES:
            self._append_progress(
                f"  최대 조정 횟수({_MAX_TARGET_FIT_PASSES}회)에 도달했습니다."
            )
            return self._try_finish_or_offer_color_mode(size)

        if not self._adjust_settings_down_to_target(target, self._pending_target_label):
            return self._try_finish_or_offer_color_mode(size)

        self._target_fit_pass += 1
        self._estimated_size_bytes = None
        self._estimated_size_label.setText("예상 최종 크기: 재산정 중...")
        self._schedule_estimate(keep_log=True)
        return True

    def _start_target_fit(self, target_bytes: int, label: str) -> None:
        self._pending_target_bytes = target_bytes
        self._pending_target_label = label
        self._target_fit_pass = 0
        self._target_fit_mode = None
        self._best_below_size = None
        self._best_below_payload = None
        self._target_color_user_declined = False
        self._final_apply_ready = False
        self._update_final_apply_btn()

        current = self._estimated_size_bytes or 0
        if _is_below_target(current, target_bytes):
            if _is_close_enough_below(current, target_bytes):
                self._finish_target_fit(current)
                return
            self._target_fit_mode = "up"
            self._remember_best_below(current)
            self._append_progress(
                f"> {label} 목표({format_file_size(target_bytes)})보다 작습니다. "
                "설정을 높여 목표에 가깝게 조정합니다..."
            )
            if not self._adjust_settings_up_to_target(target_bytes, label):
                self._finish_target_fit(current)
                return
            self._target_fit_pass = 1
            self._estimated_size_bytes = None
            self._estimated_size_label.setText("예상 최종 크기: 재산정 중...")
            self._schedule_estimate(keep_log=True)
            return

        self._target_fit_mode = "down"
        self._append_progress(
            f"> {label} 목표({format_file_size(target_bytes)})에 맞게 설정을 조정합니다..."
        )
        if not self._adjust_settings_down_to_target(target_bytes, label):
            if self._try_finish_or_offer_color_mode(self._estimated_size_bytes or -1):
                return
            return

        self._target_fit_pass = 1
        self._estimated_size_bytes = None
        self._estimated_size_label.setText("예상 최종 크기: 재산정 중...")
        self._schedule_estimate(keep_log=True)

    def _schedule_estimate(self, *, keep_log: bool = False) -> None:
        """Start estimate on the next event-loop tick (avoids worker re-entry races)."""
        QTimer.singleShot(0, lambda kl=keep_log: self._run_estimate(keep_log=kl))

    def _run_step1_estimate(self) -> None:
        if self._is_worker_busy():
            return
        self._run_estimate()

    def _run_estimate(self, *, keep_log: bool = False, _defer_count: int = 0) -> None:
        if self._worker and self._worker.isRunning():
            if _defer_count >= 20:
                self._append_progress("오류: 예상 크기 산정을 시작할 수 없습니다.")
                self._pending_target_bytes = None
                self._final_apply_ready = False
                self._set_controls_enabled(True)
                return
            QTimer.singleShot(
                50,
                lambda kl=keep_log, dc=_defer_count + 1: self._run_estimate(
                    keep_log=kl, _defer_count=dc
                ),
            )
            return

        if not keep_log:
            self._clear_progress_log()
        elif self._pending_target_bytes is not None:
            self._append_progress("  조정된 설정으로 예상 크기를 다시 계산합니다...")
        self._estimated_size_label.setText("예상 최종 크기: 계산 중...")
        self._set_controls_enabled(False)
        options = self._current_options()
        source_bytes = self._document.save_to_bytes()
        self._worker = _EstimateWorker(source_bytes, options)
        self._worker.progress.connect(self._append_progress)
        self._worker.page_progress.connect(self._on_page_progress)
        self._worker.image_progress.connect(self._on_image_progress)
        self._worker.finished.connect(self._on_estimate_finished)
        self._worker.start()

    def _on_estimate_finished(self, size: int, payload: object) -> None:
        if size < 0:
            self._set_controls_enabled(True)
            self._estimated_size_bytes = None
            self._last_reduced_payload = None
            self._estimated_size_label.setText("예상 최종 크기: 계산 실패")
            self._pending_target_bytes = None
            self._final_apply_ready = False
            return

        reduced_payload = _coerce_payload_bytes(payload)
        self._estimated_size_bytes = size
        self._last_reduced_payload = reduced_payload
        self._estimated_size_label.setText(f"예상 최종 크기: {format_file_size(size)}")
        self._fit_dialog_size()

        if self._continue_target_fit_if_needed(size):
            return

        if self._has_valid_estimate() and self._last_reduced_payload is not None:
            self._final_apply_ready = True
        self._set_controls_enabled(True)
        QTimer.singleShot(0, self._update_final_apply_btn)

    def _append_progress(self, message: str) -> None:
        self._progress_log.appendPlainText(message)
        scrollbar = self._progress_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _update_or_append_progress(self, prefix: str, suffix: str) -> None:
        text = f"{prefix}{suffix}"
        document = self._progress_log.document()
        last_block = document.lastBlock()
        if last_block.isValid() and last_block.text().startswith(prefix):
            cursor = self._progress_log.textCursor()
            cursor.setPosition(last_block.position())
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.insertText(text)
        else:
            self._append_progress(text)
        scrollbar = self._progress_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_progress_log(self) -> None:
        self._progress_log.clear()

    def _update_final_apply_btn(self) -> None:
        ready = (
            self._final_apply_ready
            and self._last_reduced_payload is not None
            and not self._is_worker_busy()
        )
        self._final_apply_btn.setEnabled(ready)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._apply_btn.setEnabled(enabled)
        self._estimate_btn.setEnabled(enabled)
        self._desired_slider.setEnabled(enabled)
        self._desired_spin.setEnabled(enabled)
        for widget in (
            self._size_slider,
            self._size_spin,
            self._quality_slider,
            self._quality_spin,
            self._dpi_slider,
            self._dpi_spin,
            self._grayscale_check,
            self._monochrome_check,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self._update_final_apply_btn()
        else:
            self._final_apply_btn.setEnabled(False)

    def _apply_reduction(self) -> None:
        if self._is_worker_busy():
            return
        if not self._has_valid_estimate():
            self._warn_estimate_required()
            return

        target_bytes = self._desired_target_bytes()
        label = self._desired_target_label()

        self._final_apply_ready = False
        self._update_final_apply_btn()
        self._clear_progress_log()
        self._append_progress("> 용량 줄이기 작업을 시작합니다...")
        self._set_controls_enabled(False)

        self._start_target_fit(target_bytes, label)

    def _confirm_final_apply(self) -> None:
        if self._is_worker_busy():
            return
        if not self._has_valid_estimate() or not self._last_reduced_payload:
            QMessageBox.warning(
                self,
                "용량 줄이기",
                "먼저 [예상 최종 크기 산정]을 실행해 주세요.",
            )
            return
        self._run_apply_reduction()

    def _run_apply_reduction(self) -> None:
        if self._is_worker_busy():
            return
        if not self._last_reduced_payload:
            self._on_apply_failed("적용할 압축 결과가 없습니다.")
            return

        self._append_progress("> 조정된 설정으로 문서에 적용합니다...")
        self._estimated_size_label.setText("적용 중...")
        self._set_controls_enabled(False)
        QTimer.singleShot(0, self._apply_payload_on_main_thread)

    def _apply_payload_on_main_thread(self) -> None:
        payload = self._last_reduced_payload
        if not payload:
            self._on_apply_failed("적용할 압축 결과가 없습니다.")
            return
        try:
            before, after = self._document.apply_reduced_payload(payload)
        except Exception as exc:
            self._on_apply_failed(str(exc))
            return
        self._on_apply_finished(before, after)

    def _on_page_progress(self, current: int, total: int) -> None:
        self._append_progress(f"  페이지 처리 중... {current}/{total}")

    def _on_image_progress(self, current: int, total: int) -> None:
        self._update_or_append_progress(_IMAGE_PROGRESS_PREFIX, f"{current}/{total}")

    def _on_apply_finished(self, before: int, after: int) -> None:
        self.result_before = before
        self.result_after = after
        self.accept()

    def _on_apply_failed(self, message: str) -> None:
        self._append_progress(f"오류: {message}")
        QMessageBox.critical(self, "용량 줄이기 오류", message)
        self._set_controls_enabled(True)
        self._update_final_apply_btn()
        self._invalidate_estimate()

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(500)
        super().closeEvent(event)
