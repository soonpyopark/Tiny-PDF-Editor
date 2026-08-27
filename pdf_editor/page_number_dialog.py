"""쪽 번호 매기기 dialog (HWP-style position + appearance)."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdf_editor.document import PdfDocument
from pdf_editor.highlight_colors import color_circle_icon_from_qcolor
from pdf_editor.page_numbers import (
    DEFAULT_PAGE_NUMBER_BACKGROUND_RGB,
    DEFAULT_PAGE_NUMBER_MARGIN_X_MM,
    DEFAULT_PAGE_NUMBER_MARGIN_Y_MM,
    DEFAULT_PAGE_NUMBER_POSITION,
    DEFAULT_PAGE_NUMBER_RGB,
    DEFAULT_PAGE_NUMBER_SIZE,
    PAGE_NUMBER_MARGIN_MM_MAX,
    PAGE_NUMBER_MARGIN_MM_MIN,
    PAGE_NUMBER_POSITIONS,
    PAGE_NUMBER_PREFIX_PRESETS,
    PAGE_NUMBER_SIZES,
    PAGE_NUMBER_STYLES,
    PAGE_NUMBER_SUFFIX_PRESETS,
    PageNumberOptions,
    format_page_number_text,
)

_POSITIONS_TOP = ("top_left", "top_center", "top_right")
_POSITIONS_BOTTOM = ("bottom_left", "bottom_center", "bottom_right")


class _PageNumberPreview(QWidget):
    """Portrait page mockup that shows the chosen number placement."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = "- 1 -"
        self._position = DEFAULT_PAGE_NUMBER_POSITION
        self._color = QColor.fromRgbF(*DEFAULT_PAGE_NUMBER_RGB)
        self._background = QColor.fromRgbF(*DEFAULT_PAGE_NUMBER_BACKGROUND_RGB)
        self._transparent_background = False
        self._show_number = True
        self._margin_x_mm = DEFAULT_PAGE_NUMBER_MARGIN_X_MM
        self._margin_y_mm = DEFAULT_PAGE_NUMBER_MARGIN_Y_MM
        self.setFixedSize(118, 168)

    def set_preview(
        self,
        text: str,
        position: str,
        color: QColor,
        show_number: bool,
        background: QColor | None = None,
        transparent_background: bool = False,
        margin_x_mm: float = DEFAULT_PAGE_NUMBER_MARGIN_X_MM,
        margin_y_mm: float = DEFAULT_PAGE_NUMBER_MARGIN_Y_MM,
    ) -> None:
        self._text = text
        self._position = position
        self._color = QColor(color)
        self._show_number = show_number
        self._transparent_background = transparent_background
        self._margin_x_mm = margin_x_mm
        self._margin_y_mm = margin_y_mm
        self._background = (
            QColor(background)
            if background is not None
            else QColor.fromRgbF(*DEFAULT_PAGE_NUMBER_BACKGROUND_RGB)
        )
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        page = QRectF(10, 8, self.width() - 20, self.height() - 16)
        painter.fillRect(self.rect(), QColor("#f3f3f3"))
        painter.setPen(QPen(QColor("#b0b0b0"), 1))
        painter.setBrush(QColor("#ececec"))
        painter.drawRect(page)

        if not self._show_number or not self._text:
            painter.end()
            return

        font = QFont()
        font.setPointSize(8 if len(self._text) > 10 else 10)
        painter.setFont(font)
        painter.setClipRect(page)
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(self._text)
        text_h = metrics.height()
        scale_x = page.width() / 210.0
        scale_y = page.height() / 297.0
        pad_x = max(2.0, self._margin_x_mm * scale_x)
        pad_y = max(2.0, self._margin_y_mm * scale_y)
        if self._position.endswith("left"):
            x = page.left() + pad_x
        elif self._position.endswith("right"):
            x = page.right() - pad_x - text_w
        else:
            x = page.center().x() - text_w / 2
        if self._position.startswith("top"):
            y = page.top() + pad_y + text_h - metrics.descent()
        else:
            y = page.bottom() - pad_y - metrics.descent()
        plate = QRectF(
            x - 3,
            y - text_h + metrics.descent(),
            text_w + 6,
            text_h,
        )
        if not self._transparent_background:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._background)
            painter.drawRect(plate)
        painter.setPen(self._color)
        painter.drawText(int(x), int(y), self._text)
        painter.end()


class PageNumberDialog(QDialog):
    """Collect page-number settings and return PageNumberOptions."""

    def __init__(self, document: PdfDocument, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document = document
        self._color = QColor.fromRgbF(*DEFAULT_PAGE_NUMBER_RGB)
        self._bg_color = QColor.fromRgbF(*DEFAULT_PAGE_NUMBER_BACKGROUND_RGB)
        self.setWindowTitle("쪽 번호 매기기")
        self.setMinimumWidth(640)
        self._build_ui()
        applied = document.load_applied_page_number_options()
        if applied is not None:
            self._apply_options(applied)
        else:
            self._sync_enabled()
            self._update_preview()

    def selected_options(self) -> PageNumberOptions:
        position = "none"
        checked = self._position_group.checkedButton()
        if checked is not None:
            position = checked.property("pageNumberPosition") or "none"
        return PageNumberOptions(
            position=position,
            style=self._style_combo.currentData() or PAGE_NUMBER_STYLES[0][0],
            add_hyphens=self._hyphen_check.isChecked(),
            prefix=self._affix_value(self._prefix_combo),
            suffix=self._affix_value(self._suffix_combo),
            start_page=self._start_page_spin.value(),
            end_page=self._end_page_spin.value(),
            start_number=self._start_number_spin.value(),
            font_size=float(self._size_combo.currentData() or DEFAULT_PAGE_NUMBER_SIZE),
            color_rgb=(self._color.redF(), self._color.greenF(), self._color.blueF()),
            background_rgb=(
                self._bg_color.redF(),
                self._bg_color.greenF(),
                self._bg_color.blueF(),
            ),
            background_transparent=self._bg_transparent_check.isChecked(),
            margin_x_mm=float(self._margin_x_spin.value()),
            margin_y_mm=float(self._margin_y_spin.value()),
        )

    def _apply_options(self, options: PageNumberOptions) -> None:
        position = options.position
        if position != "none" and position not in PAGE_NUMBER_POSITIONS:
            position = DEFAULT_PAGE_NUMBER_POSITION
        for button in self._position_group.buttons():
            if button.property("pageNumberPosition") == position:
                button.setChecked(True)
                break
        style_index = self._style_combo.findData(options.style)
        if style_index >= 0:
            self._style_combo.setCurrentIndex(style_index)
        self._hyphen_check.setChecked(options.add_hyphens)
        self._set_affix_combo(self._prefix_combo, options.prefix)
        self._set_affix_combo(self._suffix_combo, options.suffix)
        page_count = max(1, self._document.page_count)
        start_page = min(max(1, options.start_page), page_count)
        end_page = options.end_page if options.end_page > 0 else page_count
        end_page = min(max(start_page, end_page), page_count)
        self._start_page_spin.setValue(start_page)
        self._end_page_spin.setValue(end_page)
        self._start_number_spin.setValue(
            min(max(1, options.start_number), self._start_number_spin.maximum())
        )
        size = int(round(options.font_size))
        closest = min(PAGE_NUMBER_SIZES, key=lambda value: abs(value - size))
        size_index = self._size_combo.findData(closest)
        if size_index >= 0:
            self._size_combo.setCurrentIndex(size_index)
        self._color = QColor.fromRgbF(*options.color_rgb)
        self._bg_color = QColor.fromRgbF(*options.background_rgb)
        self._bg_transparent_check.setChecked(options.background_transparent)
        self._margin_x_spin.setValue(int(round(options.margin_x_mm)))
        self._margin_y_spin.setValue(int(round(options.margin_y_mm)))
        self._refresh_swatches()
        self._sync_enabled()
        self._update_preview()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        frame = QFrame()
        frame.setObjectName("pageNumberFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            """
            QFrame#pageNumberFrame {
                background: #ffffff;
                border: 1px solid #c8c8c8;
            }
            """
        )
        body = QHBoxLayout(frame)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(28)

        body.addLayout(self._build_position_column(), 0)
        body.addLayout(self._build_appearance_column(), 1)
        root.addWidget(frame, 1)
        root.addLayout(self._build_buttons_column())

    def _build_position_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        title = QLabel("번호 위치")
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        column.addWidget(title)

        self._position_group = QButtonGroup(self)
        self._position_group.setExclusive(True)
        self._preview = _PageNumberPreview()

        position_box = QWidget()
        position_box.setFixedWidth(self._preview.width())
        grid = QGridLayout(position_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(4)
        for column_index, position in enumerate(_POSITIONS_TOP):
            radio = self._make_position_radio(position)
            grid.addWidget(radio, 0, column_index, Qt.AlignmentFlag.AlignHCenter)
        grid.addWidget(self._preview, 1, 0, 1, 3, Qt.AlignmentFlag.AlignHCenter)
        for column_index, position in enumerate(_POSITIONS_BOTTOM):
            radio = self._make_position_radio(position)
            grid.addWidget(radio, 2, column_index, Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(position_box)

        margin_form = QFormLayout()
        margin_form.setContentsMargins(0, 4, 0, 0)
        margin_form.setHorizontalSpacing(8)
        margin_form.setVerticalSpacing(6)
        margin_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._margin_x_spin = self._make_margin_spin(DEFAULT_PAGE_NUMBER_MARGIN_X_MM)
        self._margin_y_spin = self._make_margin_spin(DEFAULT_PAGE_NUMBER_MARGIN_Y_MM)
        margin_form.addRow("가로 여백:", self._margin_x_spin)
        margin_form.addRow("세로 여백:", self._margin_y_spin)
        column.addLayout(margin_form)

        none_radio = QRadioButton("쪽 번호 없음")
        none_radio.setProperty("pageNumberPosition", "none")
        self._position_group.addButton(none_radio)
        self._position_group.buttonClicked.connect(self._on_position_changed)
        column.addWidget(none_radio)
        column.addStretch(1)
        return column

    def _make_position_radio(self, position: str) -> QRadioButton:
        radio = QRadioButton()
        radio.setProperty("pageNumberPosition", position)
        radio.setChecked(position == DEFAULT_PAGE_NUMBER_POSITION)
        self._position_group.addButton(radio)
        return radio

    def _make_margin_spin(self, default: float) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(int(PAGE_NUMBER_MARGIN_MM_MIN), int(PAGE_NUMBER_MARGIN_MM_MAX))
        spin.setValue(int(round(default)))
        spin.setSuffix(" mm")
        spin.setFixedWidth(80)
        spin.valueChanged.connect(self._update_preview)
        return spin

    def _make_affix_combo(
        self,
        presets: tuple[tuple[str, str], ...],
        placeholder: str,
    ) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for label, value in presets:
            combo.addItem(label, value)
        combo.setCurrentIndex(0)
        combo.lineEdit().setPlaceholderText(placeholder)
        widest = max(
            (combo.fontMetrics().horizontalAdvance(label) for label, _ in presets),
            default=0,
        )
        combo.setMinimumWidth(widest + 40)
        return combo

    @staticmethod
    def _affix_value(combo: QComboBox) -> str:
        index = combo.currentIndex()
        if index >= 0 and combo.currentText() == combo.itemText(index):
            return str(combo.itemData(index) or "")
        return combo.currentText()

    @staticmethod
    def _set_affix_combo(combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(-1)
        combo.setEditText(value)

    def _build_appearance_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(10)
        title = QLabel("번호 모양")
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        column.addWidget(title)

        style_row = QHBoxLayout()
        style_row.setSpacing(10)
        self._style_combo = QComboBox()
        for style_id, label in PAGE_NUMBER_STYLES:
            self._style_combo.addItem(label, style_id)
        self._style_combo.setMinimumWidth(110)
        self._style_combo.currentIndexChanged.connect(self._update_preview)
        self._hyphen_check = QCheckBox("줄표 넣기")
        self._hyphen_check.setChecked(True)
        self._hyphen_check.toggled.connect(self._update_preview)
        style_row.addWidget(self._style_combo)
        style_row.addWidget(self._hyphen_check)
        style_row.addStretch(1)
        column.addLayout(style_row)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._prefix_combo = self._make_affix_combo(PAGE_NUMBER_PREFIX_PRESETS, "예: page ")
        form.addRow("접두사:", self._prefix_combo)
        self._suffix_combo = self._make_affix_combo(PAGE_NUMBER_SUFFIX_PRESETS, "예: 페이지")
        form.addRow("접미사:", self._suffix_combo)
        self._prefix_combo.currentTextChanged.connect(self._update_preview)
        self._suffix_combo.currentTextChanged.connect(self._update_preview)

        page_count = max(1, self._document.page_count)
        self._start_page_spin = QSpinBox()
        self._start_page_spin.setRange(1, page_count)
        self._start_page_spin.setValue(1)
        self._start_page_spin.setFixedWidth(72)
        self._start_page_spin.valueChanged.connect(self._on_start_page_changed)
        form.addRow("쪽 번호 시작 페이지:", self._start_page_spin)

        self._end_page_spin = QSpinBox()
        self._end_page_spin.setRange(1, page_count)
        self._end_page_spin.setValue(page_count)
        self._end_page_spin.setFixedWidth(72)
        self._end_page_spin.valueChanged.connect(self._on_end_page_changed)
        form.addRow("쪽 번호 끝 페이지:", self._end_page_spin)

        self._start_number_spin = QSpinBox()
        self._start_number_spin.setRange(1, 9999)
        self._start_number_spin.setValue(1)
        self._start_number_spin.setFixedWidth(72)
        self._start_number_spin.valueChanged.connect(self._update_preview)
        form.addRow("시작 번호:", self._start_number_spin)

        self._size_combo = QComboBox()
        for size in PAGE_NUMBER_SIZES:
            self._size_combo.addItem(str(size), size)
        self._size_combo.setCurrentIndex(PAGE_NUMBER_SIZES.index(DEFAULT_PAGE_NUMBER_SIZE))
        self._size_combo.setFixedWidth(72)
        form.addRow("쪽 번호 크기:", self._size_combo)

        self._color_btn = self._make_swatch_button("쪽 번호 색상")
        self._color_btn.clicked.connect(self._pick_color)
        form.addRow("쪽 번호 색상:", self._color_btn)

        self._bg_color_btn = self._make_swatch_button("배경 색상")
        self._bg_color_btn.clicked.connect(self._pick_background_color)
        self._bg_transparent_check = QCheckBox("투명")
        self._bg_transparent_check.setChecked(True)
        self._bg_transparent_check.toggled.connect(self._on_background_transparent_toggled)
        bg_row = QWidget()
        bg_layout = QHBoxLayout(bg_row)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        bg_layout.setSpacing(8)
        bg_layout.addWidget(self._bg_color_btn)
        bg_layout.addWidget(self._bg_transparent_check)
        bg_layout.addStretch(1)
        form.addRow("배경 색상:", bg_row)
        self._refresh_swatches()
        column.addLayout(form)
        column.addStretch(1)
        return column

    def _build_buttons_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        button_style = """
            QPushButton {
                padding: 4px 10px;
                min-height: 26px;
                max-height: 26px;
                border: 2px solid #c8c8c8;
                border-radius: 3px;
            }
            QPushButton:default {
                border: 2px solid #3b82f6;
            }
        """
        self._insert_btn = QPushButton("넣기(&D)")
        self._insert_btn.setDefault(True)
        self._insert_btn.setAutoDefault(True)
        self._insert_btn.setFixedWidth(86)
        self._insert_btn.setStyleSheet(button_style)
        self._insert_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("취소")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setFixedWidth(86)
        cancel_btn.setStyleSheet(button_style)
        cancel_btn.clicked.connect(self.reject)
        column.addWidget(self._insert_btn)
        column.addWidget(cancel_btn)
        column.addStretch(1)
        return column

    def _on_position_changed(self) -> None:
        self._sync_enabled()
        self._update_preview()

    def _on_start_page_changed(self, value: int) -> None:
        if value > self._end_page_spin.value():
            self._end_page_spin.blockSignals(True)
            self._end_page_spin.setValue(value)
            self._end_page_spin.blockSignals(False)

    def _on_end_page_changed(self, value: int) -> None:
        if value < self._start_page_spin.value():
            self._start_page_spin.blockSignals(True)
            self._start_page_spin.setValue(value)
            self._start_page_spin.blockSignals(False)

    def _sync_enabled(self) -> None:
        options = self.selected_options()
        enabled = not options.remove_only
        for widget in (
            self._style_combo,
            self._hyphen_check,
            self._prefix_combo,
            self._suffix_combo,
            self._start_page_spin,
            self._end_page_spin,
            self._start_number_spin,
            self._size_combo,
            self._color_btn,
            self._bg_transparent_check,
            self._margin_y_spin,
        ):
            widget.setEnabled(enabled)
        self._bg_color_btn.setEnabled(enabled and not self._bg_transparent_check.isChecked())
        self._margin_x_spin.setEnabled(
            enabled and not options.position.endswith("center")
        )

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "쪽 번호 색상")
        if not chosen.isValid():
            return
        self._color = chosen
        self._refresh_swatches()
        self._update_preview()

    def _on_background_transparent_toggled(self) -> None:
        self._sync_enabled()
        self._update_preview()

    def _pick_background_color(self) -> None:
        chosen = QColorDialog.getColor(self._bg_color, self, "배경 색상")
        if not chosen.isValid():
            return
        self._bg_color = chosen
        self._refresh_swatches()
        self._update_preview()

    def _make_swatch_button(self, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(36, 24)
        button.setToolTip(tooltip)
        return button

    def _refresh_swatches(self) -> None:
        self._style_swatch(self._color_btn, self._color)
        self._style_swatch(self._bg_color_btn, self._bg_color)

    @staticmethod
    def _style_swatch(button: QPushButton, color: QColor) -> None:
        button.setIcon(color_circle_icon_from_qcolor(color, size=16))
        button.setIconSize(button.icon().actualSize(button.size()))
        button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {color.name()};
                border: 1px solid #888;
            }}
            """
        )

    def _update_preview(self) -> None:
        options = self.selected_options()
        text = format_page_number_text(
            options.start_number,
            options.style,
            options.add_hyphens,
            options.prefix,
            options.suffix,
        )
        self._preview.set_preview(
            text,
            options.position,
            self._color,
            show_number=not options.remove_only,
            background=self._bg_color,
            transparent_background=options.background_transparent,
            margin_x_mm=options.margin_x_mm,
            margin_y_mm=options.margin_y_mm,
        )
