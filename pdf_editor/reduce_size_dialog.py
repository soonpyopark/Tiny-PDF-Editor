"""Dialog for PDF size reduction with estimation."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    COMPRESS_MODE_DATA_ONLY,
    COMPRESS_MODE_STANDARD,
    DocumentReduceProfile,
    GEOMETRY_MODE_BOTH,
    GEOMETRY_MODE_CONTENT_ONLY,
    GEOMETRY_MODE_PAGE_ONLY,
    PRESET_OPTIONS,
    PdfDocument,
    RASTER_FORMAT_AUTO,
    RASTER_FORMAT_GRAY_JPEG,
    RASTER_FORMAT_JPEG,
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
_STEP_BLOCK_SPACING = 12
_STEP_REGION_GAP = 14  # equal whitespace above each [N단계] header
_STEP_LABEL_HEIGHT = 14
_SETTINGS_HEADER_HEIGHT = 44
_STEP1_BTN_RELOCATE_SAVED_HEIGHT = 14  # root spacing removed when btn joins step1 section
# Progress log height offset kept after [0단계] guide section removal (avoids refilling that space).
_REMOVED_STEP0_SAVED_HEIGHT = _STEP_LABEL_HEIGHT + _STEP_BLOCK_SPACING + 40
_DESIRED_PANEL_VERTICAL_MARGIN = 6  # original loose panel grid top/bottom margin (each side)
_DESIRED_PANEL_INNER_MARGIN = 4  # compact panel top/bottom padding (each side)
_DESIRED_PANEL_COMPACT_SAVED_HEIGHT = (
    (_DESIRED_PANEL_VERTICAL_MARGIN - _DESIRED_PANEL_INNER_MARGIN) * 2
)
_DESIRED_PANEL_STRETCH_SAVED_HEIGHT = 40  # inflated layout height beyond padded compact row (~76 - 36)
_DESIRED_PANEL_SAVED_HEIGHT = _DESIRED_PANEL_STRETCH_SAVED_HEIGHT
_DESIRED_PANEL_SIZEHINT_OVERHEAD = (
    _DESIRED_PANEL_SAVED_HEIGHT - _DESIRED_PANEL_COMPACT_SAVED_HEIGHT
)
_EXTRA_TERMINAL_HEIGHT = 48
_PROGRESS_LOG_MIN_HEIGHT = (
    110
    + _SETTINGS_HEADER_HEIGHT
    + _STEP1_BTN_RELOCATE_SAVED_HEIGHT
    + _EXTRA_TERMINAL_HEIGHT
    + _DESIRED_PANEL_SAVED_HEIGHT
    - _REMOVED_STEP0_SAVED_HEIGHT
)
_PROGRESS_LOG_MAX_HEIGHT = (
    150
    + _SETTINGS_HEADER_HEIGHT
    + _STEP1_BTN_RELOCATE_SAVED_HEIGHT
    + _EXTRA_TERMINAL_HEIGHT
    + _DESIRED_PANEL_SAVED_HEIGHT
    - _REMOVED_STEP0_SAVED_HEIGHT
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
_RASTERIZE_DEFAULT_DPI = 72
_RASTERIZE_DEFAULT_QUALITY = 30
_RASTERIZE_DEFAULT_SIZE = 50
_DATA_ONLY_DEFAULT_DPI = 72
_DATA_ONLY_DEFAULT_QUALITY = 45
_NO_RASTERIZE_WARNING_MESSAGE = "경고 메시지 없음\n "
_NO_PROFILE_INFO_MESSAGE = "안내 메시지 없음"
_WARNING_BOX_LINE_HEIGHT = 20
_WARNING_BOX_PADDING_V = 16
_RASTERIZE_WARNING_LINES = 2
_RASTERIZE_WARNING_BOX_HEIGHT = (
    _WARNING_BOX_LINE_HEIGHT * _RASTERIZE_WARNING_LINES + _WARNING_BOX_PADDING_V
)
_ESTIMATE_REQUIRED_MESSAGE = (
    "먼저 [예상 최종 크기 산정]을 실행해 주세요."
)


def _make_step_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(_STEP_HEADER_FONT)
    label.setFixedHeight(_STEP_LABEL_HEIGHT)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return label


def _configure_step_layout(layout: QVBoxLayout) -> None:
    layout.setContentsMargins(0, _STEP_REGION_GAP, 0, 0)
    layout.setSpacing(_STEP_BLOCK_SPACING)


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


def _make_rasterize_warning_label() -> QLabel:
    label = QLabel(_NO_RASTERIZE_WARNING_MESSAGE)
    label.setWordWrap(True)
    label.setFixedHeight(_RASTERIZE_WARNING_BOX_HEIGHT)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    label.setStyleSheet(
        "color: #b71c1c; font-size: 12px; background: #ffebee;"
        "border: 1px solid #ef9a9a; border-radius: 6px; padding: 8px 10px;"
    )
    return label


def _rasterize_warning_text(*, active: bool, raster_format: str) -> str:
    if not active:
        return _NO_RASTERIZE_WARNING_MESSAGE
    return (
        "픽셀 이미지화가 켜져 있습니다. 텍스트 검색·복사·선택이 불가능해집니다.\n"
        f"저장 포맷: {raster_format}. 용량이 늘면 사이즈·DPI·품질을 낮추거나 "
        "회색 JPEG를 사용해 보세요."
    )


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


def _format_scale_percent(scale: float) -> str:
    percent = round(scale * 100, 1)
    if percent.is_integer():
        return f"{int(percent)}%"
    return f"{percent}%"


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
        root.setContentsMargins(18, 0, 18, 18)
        root.setSpacing(0)

        self._advanced_panel = QFrame()
        self._advanced_panel.setStyleSheet(_PANEL_FRAME_STYLE)
        self._advanced_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
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

        geometry_label = _make_advanced_label("크기 조정")
        self._geometry_mode_combo = QComboBox()
        self._geometry_mode_combo.addItem("페이지·내용 함께", GEOMETRY_MODE_BOTH)
        self._geometry_mode_combo.addItem("페이지 크기만", GEOMETRY_MODE_PAGE_ONLY)
        self._geometry_mode_combo.addItem("내용 크기만", GEOMETRY_MODE_CONTENT_ONLY)
        self._geometry_mode_combo.currentIndexChanged.connect(self._on_advanced_changed)
        advanced_grid.addWidget(geometry_label, 3, 0)
        advanced_grid.addWidget(self._geometry_mode_combo, 3, 1, 1, 2)

        control_row_height = self._size_spin.sizeHint().height()
        for label in (size_label, quality_label, dpi_label, geometry_label):
            label.setFixedHeight(control_row_height)

        self._reduce_profile = document.reduce_profile()
        self._embedded_scale_warning = QLabel(_NO_PROFILE_INFO_MESSAGE)
        self._embedded_scale_warning.setWordWrap(True)
        self._embedded_scale_warning.setMinimumHeight(36)
        self._embedded_scale_warning.setStyleSheet(
            "color: #8a6d00; font-size: 12px; background: #fff8e1;"
            "border: 1px solid #ffe082; border-radius: 6px; padding: 8px 10px;"
        )
        advanced_layout.addWidget(self._embedded_scale_warning)

        self._grayscale_check = QCheckBox("회색조로 변환 (Grayscale)")
        self._grayscale_check.toggled.connect(self._on_grayscale_toggled)
        self._monochrome_check = QCheckBox("단색조로 변환 (Monochrome)")
        self._monochrome_check.toggled.connect(self._on_monochrome_toggled)
        self._rasterize_check = QCheckBox("픽셀 이미지화 변환 (Rasterize)")
        self._rasterize_check.toggled.connect(self._on_rasterize_toggled)

        color_row = QHBoxLayout()
        color_row.setSpacing(16)
        color_row.addWidget(self._grayscale_check)
        color_row.addWidget(self._monochrome_check)
        color_row.addWidget(self._rasterize_check)
        color_row.addStretch(1)

        self._data_only_check = QCheckBox("데이터만 압축 (72dpi, Acrobat식)")
        self._data_only_check.setToolTip(
            "레이아웃·검색은 유지하고 임베디드 이미지(미세 조각 포함)만 재압축합니다."
        )
        self._data_only_check.toggled.connect(self._on_data_only_toggled)
        data_only_row = QHBoxLayout()
        data_only_row.setSpacing(16)
        data_only_row.addWidget(self._data_only_check)
        data_only_row.addStretch(1)

        raster_format_label = _make_advanced_label("픽셀 포맷")
        self._raster_format_combo = QComboBox()
        self._raster_format_combo.addItem("자동", RASTER_FORMAT_AUTO)
        self._raster_format_combo.addItem("JPEG (컬러)", RASTER_FORMAT_JPEG)
        self._raster_format_combo.addItem("회색 JPEG", RASTER_FORMAT_GRAY_JPEG)
        self._raster_format_combo.currentIndexChanged.connect(self._on_advanced_changed)
        self._raster_format_combo.setEnabled(False)
        advanced_grid.addWidget(raster_format_label, 4, 0)
        advanced_grid.addWidget(self._raster_format_combo, 4, 1, 1, 2)
        raster_format_label.setFixedHeight(control_row_height)

        self._rasterize_warning = _make_rasterize_warning_label()

        advanced_layout.addLayout(advanced_grid)
        advanced_layout.addLayout(color_row)
        advanced_layout.addLayout(data_only_row)
        advanced_layout.addWidget(self._rasterize_warning)

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

        step1_section = QWidget()
        step1_section_layout = QVBoxLayout(step1_section)
        _configure_step_layout(step1_section_layout)
        step1_section_layout.addWidget(_make_step_label("[1단계] 예상 최종 크기 산정"))
        step1_section_layout.addWidget(self._advanced_panel)

        step1_row = QWidget()
        step1_layout = QHBoxLayout(step1_row)
        step1_layout.setContentsMargins(0, 0, 0, 0)
        step1_layout.setSpacing(_STEP_BLOCK_SPACING)

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
        step1_layout.addWidget(self._estimated_size_label)
        step1_section_layout.addWidget(step1_row)
        root.addWidget(step1_section)

        step2_section = QWidget()
        step2_layout = QVBoxLayout(step2_section)
        _configure_step_layout(step2_layout)

        step2_layout.addWidget(
            _make_step_label("[2단계] (선택) 희망 최종 용량 설정 및 용량 줄이기 자동 반복")
        )

        desired_panel = QFrame()
        desired_panel.setStyleSheet(_PANEL_FRAME_STYLE)
        desired_grid = QGridLayout(desired_panel)
        desired_grid.setContentsMargins(
            14, _DESIRED_PANEL_INNER_MARGIN, 14, _DESIRED_PANEL_INNER_MARGIN
        )
        desired_grid.setHorizontalSpacing(10)
        desired_grid.setVerticalSpacing(0)
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

        row_align = Qt.AlignmentFlag.AlignVCenter
        desired_grid.addWidget(desired_label, 0, 0, alignment=row_align)
        desired_grid.addWidget(self._desired_slider, 0, 1, alignment=row_align)
        desired_grid.addWidget(self._desired_spin, 0, 2, alignment=row_align)
        desired_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        desired_panel.setFixedHeight(
            control_row_height + 2 + _DESIRED_PANEL_INNER_MARGIN * 2
        )

        self._apply_btn = QPushButton("용량 줄이기 반복 실행")
        self._apply_btn.setMinimumHeight(40)
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.setStyleSheet(outline_btn_style)
        self._apply_btn.clicked.connect(self._apply_reduction)

        step2_layout.addWidget(desired_panel)
        apply_row = QHBoxLayout()
        apply_row.setContentsMargins(0, 0, 0, 0)
        apply_row.setSpacing(0)
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

        step3_section = QWidget()
        step3_layout = QVBoxLayout(step3_section)
        _configure_step_layout(step3_layout)
        step3_layout.addWidget(_make_step_label("[3단계] 최종 적용 하기"))
        step3_layout.addWidget(self._progress_log)

        self._final_apply_btn = QPushButton("최종 적용 하기")
        self._final_apply_btn.setMinimumHeight(40)
        self._final_apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._final_apply_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._final_apply_btn.setEnabled(False)
        self._final_apply_btn.clicked.connect(self._confirm_final_apply)
        final_apply_row = QHBoxLayout()
        final_apply_row.setContentsMargins(0, 0, 0, 0)
        final_apply_row.setSpacing(0)
        final_apply_row.addWidget(self._final_apply_btn)
        final_apply_row.addStretch(1)
        step3_layout.addLayout(final_apply_row)
        root.addWidget(step3_section)

        action_btn_width = max(
            self._estimate_btn.sizeHint().width(),
            self._apply_btn.sizeHint().width(),
            self._final_apply_btn.sizeHint().width(),
        )
        self._estimate_btn.setFixedWidth(action_btn_width)
        self._apply_btn.setFixedWidth(action_btn_width)
        self._final_apply_btn.setFixedWidth(action_btn_width)

        self._apply_default_options()
        self._apply_profile_defaults()
        self._sync_profile_control_locks()
        self._fit_dialog_size()

    def _fit_dialog_size(self) -> None:
        """Keep dialog width fixed; adjust height only when content changes."""
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        margins = layout.contentsMargins()
        height = layout.sizeHint().height() + margins.top() + margins.bottom()
        height -= _DESIRED_PANEL_SIZEHINT_OVERHEAD
        self.setFixedSize(_DIALOG_WIDTH, height)

    def _schedule_fit_dialog_size(self) -> None:
        """Re-measure after visibility or wrapped-label text changes."""
        QTimer.singleShot(0, self._fit_dialog_size)

    def _invalidate_estimate(self) -> None:
        self._estimated_size_bytes = None
        self._last_reduced_payload = None
        self._final_apply_ready = False
        if hasattr(self, "_estimated_size_label"):
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

    def _apply_profile_defaults(self) -> None:
        profile = self._reduce_profile
        if profile.prefers_page_only:
            self._geometry_mode_combo.blockSignals(True)
            for index in range(self._geometry_mode_combo.count()):
                if self._geometry_mode_combo.itemData(index) == GEOMETRY_MODE_PAGE_ONLY:
                    self._geometry_mode_combo.setCurrentIndex(index)
                    break
            self._geometry_mode_combo.blockSignals(False)
        if profile.prefers_compression_only:
            self._block_advanced_signals(True)
            self._size_slider.setValue(100)
            self._size_spin.setValue(100)
            self._block_advanced_signals(False)
        self._update_reduce_profile_warning()

    def _target_fit_mode_label(self) -> str:
        if self._data_only_check.isChecked():
            return "데이터만 압축"
        return "화면 보호"

    def _uses_safe_compression_only(self) -> bool:
        if self._rasterize_check.isChecked():
            return False
        if self._data_only_check.isChecked():
            return True
        return self._reduce_profile.prefers_compression_only

    def _sync_profile_control_locks(self) -> None:
        """Keep image size at 100% for Distiller/micro-image PDFs (geometry breaks if lowered)."""
        lock_size = self._uses_safe_compression_only()
        rasterize = self._rasterize_check.isChecked()
        data_only = self._data_only_check.isChecked()
        for widget in (self._size_slider, self._size_spin):
            widget.setEnabled(not lock_size)
        self._geometry_mode_combo.setEnabled(not rasterize and not data_only)
        self._raster_format_combo.setEnabled(rasterize)
        self._data_only_check.setEnabled(not rasterize)
        self._rasterize_check.setEnabled(not data_only)
        if lock_size:
            self._size_slider.blockSignals(True)
            self._size_spin.blockSignals(True)
            self._size_slider.setValue(100)
            self._size_spin.setValue(100)
            self._size_slider.blockSignals(False)
            self._size_spin.blockSignals(False)

    def _block_advanced_signals(self, block: bool) -> None:
        for widget in (
            self._size_slider,
            self._size_spin,
            self._quality_slider,
            self._quality_spin,
            self._dpi_slider,
            self._dpi_spin,
            self._geometry_mode_combo,
            self._grayscale_check,
            self._monochrome_check,
            self._raster_format_combo,
            self._data_only_check,
        ):
            widget.blockSignals(block)

    def _apply_data_only_defaults(self) -> None:
        self._block_advanced_signals(True)
        self._size_slider.setValue(100)
        self._size_spin.setValue(100)
        self._quality_slider.setValue(_DATA_ONLY_DEFAULT_QUALITY)
        self._quality_spin.setValue(_DATA_ONLY_DEFAULT_QUALITY)
        self._dpi_slider.setValue(_DATA_ONLY_DEFAULT_DPI)
        self._dpi_spin.setValue(_DATA_ONLY_DEFAULT_DPI)
        self._geometry_mode_combo.blockSignals(True)
        for index in range(self._geometry_mode_combo.count()):
            if self._geometry_mode_combo.itemData(index) == GEOMETRY_MODE_PAGE_ONLY:
                self._geometry_mode_combo.setCurrentIndex(index)
                break
        self._geometry_mode_combo.blockSignals(False)
        self._block_advanced_signals(False)
        self._active_preset = "data_only"

    def _on_data_only_toggled(self, checked: bool) -> None:
        if checked:
            if self._rasterize_check.isChecked():
                self._rasterize_check.blockSignals(True)
                self._rasterize_check.setChecked(False)
                self._rasterize_check.blockSignals(False)
                self._update_rasterize_warning(False)
            reply = QMessageBox.question(
                self,
                "데이터만 압축",
                "미세 이미지 조각을 포함해 모든 임베디드 이미지를 "
                "화면 크기 기준으로 재압축합니다.\n\n"
                "레이아웃·텍스트 검색은 유지되지만, "
                "일부 PDF에서는 글자 주변이 흐릿해질 수 있습니다.\n\n"
                "계속하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._data_only_check.blockSignals(True)
                self._data_only_check.setChecked(False)
                self._data_only_check.blockSignals(False)
                checked = False
            else:
                self._apply_data_only_defaults()
        self._sync_profile_control_locks()
        self._on_advanced_changed()

    def _apply_rasterize_defaults(self) -> None:
        self._block_advanced_signals(True)
        self._size_slider.setValue(_RASTERIZE_DEFAULT_SIZE)
        self._size_spin.setValue(_RASTERIZE_DEFAULT_SIZE)
        self._quality_slider.setValue(_RASTERIZE_DEFAULT_QUALITY)
        self._quality_spin.setValue(_RASTERIZE_DEFAULT_QUALITY)
        self._dpi_slider.setValue(_RASTERIZE_DEFAULT_DPI)
        self._dpi_spin.setValue(_RASTERIZE_DEFAULT_DPI)
        self._block_advanced_signals(False)
        self._active_preset = "custom"

    def _on_rasterize_toggled(self, checked: bool) -> None:
        if checked:
            if self._data_only_check.isChecked():
                self._data_only_check.blockSignals(True)
                self._data_only_check.setChecked(False)
                self._data_only_check.blockSignals(False)
            reply = QMessageBox.question(
                self,
                "픽셀 이미지화 변환",
                "픽셀 이미지화 변환을 사용하면 페이지가 이미지로 저장됩니다.\n\n"
                "텍스트 검색·텍스트 복사·텍스트 선택이 불가능해집니다.\n\n"
                "이 옵션을 사용하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._rasterize_check.blockSignals(True)
                self._rasterize_check.setChecked(False)
                self._rasterize_check.blockSignals(False)
                checked = False
            else:
                self._apply_rasterize_defaults()
        self._update_rasterize_warning(checked)
        self._sync_profile_control_locks()
        self._on_advanced_changed()

    def _update_rasterize_warning(self, active: bool | None = None) -> None:
        if active is None:
            active = self._rasterize_check.isChecked()
        self._rasterize_warning.setText(
            _rasterize_warning_text(
                active=active,
                raster_format=self._raster_format_combo.currentText(),
            )
        )

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

    def _update_reduce_profile_warning(self) -> None:
        profile = self._reduce_profile
        if not profile.prefers_page_only:
            self._embedded_scale_warning.setText(_NO_PROFILE_INFO_MESSAGE)
            return

        parts: list[str] = []
        if profile.prefers_compression_only:
            if profile.distiller_print_pdf:
                parts.append("인쇄용 Distiller PDF")
            micro_pct = round(profile.micro_image_ratio * 100)
            if micro_pct > 0:
                parts.append(f"미세 이미지 조각 {micro_pct}%")
        if profile.fullpage_raster_ratio >= 0.5:
            ratio = round(profile.fullpage_raster_ratio * 100)
            parts.append(f"페이지당 큰 이미지 1장 형태({ratio}% 샘플)")
        if profile.publisher_flip_scale is not None:
            parts.append(
                f"출판용 Y축 뒤집기 배율 {_format_scale_percent(profile.publisher_flip_scale)}"
            )
        if profile.embedded_uniform_scale is not None:
            parts.append(
                f"내장 배율 {_format_scale_percent(profile.embedded_uniform_scale)}"
            )

        detail = ", ".join(parts) if parts else "특수 페이지 변환"
        if profile.prefers_compression_only:
            extra = (
                " [데이터만 압축]을 켜면 Acrobat과 유사한 용량 절감이 가능할 수 있습니다."
                if profile.recommends_data_only_compress
                else ""
            )
            self._embedded_scale_warning.setText(
                f"인쇄/혼합 레이아웃 PDF로 보입니다 ({detail}). "
                "글자 주변 미세 이미지 보호를 위해 [이미지 사이즈 100%]와 "
                "[페이지 크기만]으로 설정했습니다. 이미지 압축은 유지됩니다. "
                "자동 반복 시에는 품질·DPI만 조정합니다. "
                f"화면이 깨지면 [픽셀 이미지화 변환]을 검토해 보세요.{extra}"
            )
        elif profile.recommends_data_only_compress:
            self._embedded_scale_warning.setText(
                f"인쇄용 Distiller PDF로 보입니다 ({detail}). "
                "용량을 크게 줄이려면 [데이터만 압축]을 사용해 보세요. "
                "레이아웃·검색은 유지됩니다."
            )
        else:
            self._embedded_scale_warning.setText(
                f"출판/인쇄용 PDF로 보입니다 ({detail}). "
                "기본값을 [페이지 크기만]으로 설정했습니다. "
                "이미지 압축은 유지되며, 필요하면 [크기 조정] 방식을 바꿔 주세요."
            )

    def _current_geometry_mode(self) -> str:
        if self._rasterize_check.isChecked() or self._data_only_check.isChecked():
            return GEOMETRY_MODE_PAGE_ONLY
        value = self._geometry_mode_combo.currentData()
        if isinstance(value, str):
            return value
        return GEOMETRY_MODE_BOTH

    def _current_raster_format(self) -> str:
        value = self._raster_format_combo.currentData()
        if isinstance(value, str):
            return value
        return RASTER_FORMAT_AUTO

    def _current_compress_mode(self) -> str:
        if self._data_only_check.isChecked():
            return COMPRESS_MODE_DATA_ONLY
        return COMPRESS_MODE_STANDARD

    def _on_advanced_changed(self) -> None:
        self._update_rasterize_warning()
        self._active_preset = "custom"
        self._invalidate_estimate()

    def _current_options(self) -> ReduceSizeOptions:
        return ReduceSizeOptions(
            preset=self._active_preset,
            jpeg_quality=self._quality_slider.value(),
            max_dpi=self._dpi_spin.value(),
            image_size_percent=self._size_slider.value(),
            geometry_mode=self._current_geometry_mode(),
            grayscale=self._grayscale_check.isChecked(),
            monochrome=self._monochrome_check.isChecked(),
            rasterize=self._rasterize_check.isChecked(),
            raster_format=self._current_raster_format(),
            compress_mode=self._current_compress_mode(),
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
        if self._uses_safe_compression_only():
            image_size_percent = 100
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

        lock_size = self._uses_safe_compression_only()
        size = self._size_slider.value()
        quality = self._quality_slider.value()
        dpi = self._dpi_spin.value()

        ratio = (target_bytes / current) * _TARGET_UNDERSHOOT
        factor = ratio ** 0.35
        new_size = 100 if lock_size else max(1, min(100, round(size * factor)))
        new_quality = max(_MIN_QUALITY, min(_MAX_QUALITY, round(quality * factor)))
        new_dpi = max(_MIN_DPI, min(_MAX_DPI, round(dpi * factor)))

        if ratio < 1.0:
            if not lock_size and new_size == size and size > 1:
                new_size = size - 1
            if new_quality == quality and quality > _MIN_QUALITY:
                new_quality = quality - 1
            if new_dpi == dpi and dpi > _MIN_DPI:
                new_dpi = dpi - 1

        if lock_size:
            new_size = 100

        if lock_size:
            stuck = new_quality == quality and new_dpi == dpi
        else:
            stuck = new_size == size and new_quality == quality and new_dpi == dpi
        if stuck:
            if lock_size:
                self._append_progress(
                    f"  {self._target_fit_mode_label()} 모드: 품질·DPI를 더 낮출 수 없습니다 "
                    f"({format_file_size(current)})."
                )
            else:
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
        if lock_size:
            self._append_progress(
                f"  설정 조정 ({self._target_fit_pass + 1}차, {self._target_fit_mode_label()}): "
                f"품질 {quality}% → {new_quality}%, DPI {dpi} → {new_dpi} "
                "(이미지 사이즈 100% 유지)"
            )
        else:
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

        lock_size = self._uses_safe_compression_only()
        size = self._size_slider.value()
        quality = self._quality_slider.value()
        dpi = self._dpi_spin.value()

        ratio = (target_bytes / current) * _TARGET_UNDERSHOOT
        factor = ratio ** 0.35
        new_size = 100 if lock_size else max(1, min(100, round(size * factor)))
        new_quality = max(_MIN_QUALITY, min(_MAX_QUALITY, round(quality * factor)))
        new_dpi = max(_MIN_DPI, min(_MAX_DPI, round(dpi * factor)))

        if ratio > 1.0:
            if not lock_size and new_size == size and size < 100:
                new_size = size + 1
            if new_quality == quality and quality < _MAX_QUALITY:
                new_quality = quality + 1
            if new_dpi == dpi and dpi < _MAX_DPI:
                new_dpi = dpi + 1

        if lock_size:
            new_size = 100

        if lock_size:
            stuck = new_quality == quality and new_dpi == dpi
        else:
            stuck = new_size == size and new_quality == quality and new_dpi == dpi
        if stuck:
            if lock_size:
                mode_label = self._target_fit_mode_label()
                self._append_progress(
                    f"  {mode_label} 모드: 품질·DPI를 더 높일 수 없습니다 "
                    f"({format_file_size(current)})."
                )
            else:
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
        if lock_size:
            self._append_progress(
                f"  설정 상향 ({self._target_fit_pass + 1}차, {self._target_fit_mode_label()}): "
                f"품질 {quality}% → {new_quality}%, DPI {dpi} → {new_dpi} "
                "(이미지 사이즈 100% 유지)"
            )
        else:
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
            note = (
                f"참고: 예상 크기 {format_file_size(size)}로 "
                f"{label} 목표({format_file_size(target)}) 미만에 도달하지 못했습니다. "
                "현재 설정으로 [최종 적용 하기]를 사용할 수 있습니다."
            )
            if self._uses_safe_compression_only():
                note += " (화면 보호 모드: 이미지 사이즈는 변경하지 않았습니다.)"
            self._append_progress(note)
        else:
            self._final_apply_ready = False
            note = (
                f"참고: 예상 크기 {format_file_size(size)}로 "
                f"{label} 목표({format_file_size(target)}) 미만에 도달하지 못했습니다."
            )
            if self._uses_safe_compression_only():
                note += " (화면 보호 모드: 이미지 사이즈는 변경하지 않았습니다.)"
            self._append_progress(note)

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

    def _log_follows_tail(self) -> bool:
        """True when the user has not scrolled up to read earlier log lines."""
        scrollbar = self._progress_log.verticalScrollBar()
        return scrollbar.maximum() - scrollbar.value() <= 4

    def _scroll_log_to_end_if_following(self) -> None:
        if not self._log_follows_tail():
            return
        scrollbar = self._progress_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _append_progress(self, message: str) -> None:
        self._progress_log.appendPlainText(message)
        self._scroll_log_to_end_if_following()

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
            self._progress_log.appendPlainText(text)
        self._scroll_log_to_end_if_following()

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
            self._geometry_mode_combo,
            self._grayscale_check,
            self._monochrome_check,
            self._rasterize_check,
            self._raster_format_combo,
            self._data_only_check,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self._update_final_apply_btn()
            self._sync_profile_control_locks()
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
        if self._rasterize_check.isChecked():
            reply = QMessageBox.question(
                self,
                "픽셀 이미지화 변환",
                "픽셀 이미지화 변환으로 저장하면 텍스트 검색·복사·선택이 "
                "불가능해집니다.\n\n최종 적용하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
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
