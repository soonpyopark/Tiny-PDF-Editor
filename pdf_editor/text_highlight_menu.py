"""Context-menu UI for applying text highlights."""



from __future__ import annotations



from collections.abc import Callable, Sequence

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QSize, QTimer, pyqtSignal

from PyQt6.QtGui import QCursor, QIcon, QMouseEvent, QPainter, QPen, QColor, QPixmap

from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from pdf_editor.highlight_colors import (
    HIGHLIGHT_PRESET_ORDER,
    UNDERLINE_PRESET_ORDER,
    color_circle_icon,
    preferred_highlight_icon,
    preferred_underline_icon,
    underline_color_circle_icon,
)



_MENU_ITEM_TEXT_COLOR = "#333333"

_MENU_ITEM_HOVER_BG = "#ebebeb"

_MENU_ITEM_NORMAL_BG = "#ffffff"



TEXT_SELECTION_MENU_STYLE = f"""

    QMenu {{

        background-color: #ffffff;

        color: {_MENU_ITEM_TEXT_COLOR};

    }}

    QMenu::item {{

        color: {_MENU_ITEM_TEXT_COLOR};

        background-color: transparent;

        padding: 4px 24px 4px 12px;

    }}

    QMenu::item:selected {{

        background-color: {_MENU_ITEM_HOVER_BG};

        color: {_MENU_ITEM_TEXT_COLOR};

    }}

    QMenu::item:disabled {{

        color: #999999;

    }}

"""



_HIGHLIGHT_COLOR_MENU_STYLE = """

    QMenu {

        background-color: #ffffff;

        color: #333333;

    }

    QMenu::item {

        background-color: transparent;

        padding: 0px;

    }

    QMenu::item:selected {

        background-color: transparent;

    }

"""



_COLOR_PICKER_TOOL_BUTTON_STYLE = f"""
    QToolButton {{
        background-color: transparent;
        border: none;
        border-radius: 3px;
    }}
    QToolButton:hover {{
        background-color: {_MENU_ITEM_HOVER_BG};
    }}
"""

_SUBMENU_ARROW_ICON_PX = 10


def _submenu_arrow_icon(*, size: int = _SUBMENU_ARROW_ICON_PX) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(_MENU_ITEM_TEXT_COLOR), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    mid_y = size // 2
    painter.drawLine(2, 2, size - 3, mid_y)
    painter.drawLine(size - 3, mid_y, 2, size - 2)
    painter.end()
    return QIcon(pixmap)





def _dismiss_popup_menus(*menus: QMenu) -> None:

    for menu in menus:

        menu.close()

    popup = QApplication.activePopupWidget()

    while popup is not None:

        popup.close()

        popup = QApplication.activePopupWidget()


def _reset_markup_menu_hover(menu: QMenu) -> None:
    menu._block_markup_hover = True
    menu._hover_arm_pos = QCursor.pos()
    menu.setActiveAction(None)
    for row in getattr(menu, "_markup_rows", []):
        row.force_set_hovered(False)
    QTimer.singleShot(0, lambda: _keep_markup_hover_cleared(menu))


def _keep_markup_hover_cleared(menu: QMenu) -> None:
    if not menu.isVisible():
        return
    menu.setActiveAction(None)
    for row in getattr(menu, "_markup_rows", []):
        row.force_set_hovered(False)


class _MarkupMenuHoverFilter(QObject):
    """Defer row hover until the pointer actually moves after the menu opens."""

    def __init__(self, menu: QMenu) -> None:
        super().__init__(menu)
        menu.setMouseTracking(True)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is not self.parent():
            return False

        menu = self.parent()
        if not isinstance(menu, QMenu):
            return False

        if event.type() == QEvent.Type.MouseMove:
            global_pos = (
                event.globalPosition().toPoint()
                if isinstance(event, QMouseEvent)
                else QCursor.pos()
            )
            if getattr(menu, "_block_markup_hover", False):
                arm = getattr(menu, "_hover_arm_pos", None)
                # Ignore the synthetic move at the open cursor; require real travel.
                if arm is not None and (global_pos - arm).manhattanLength() < 6:
                    menu.setActiveAction(None)
                    for row in getattr(menu, "_markup_rows", []):
                        row.force_set_hovered(False)
                    return False
                menu._block_markup_hover = False
            for row in getattr(menu, "_markup_rows", []):
                row.sync_hover(global_pos)
            return False

        if event.type() == QEvent.Type.Leave:
            for row in getattr(menu, "_markup_rows", []):
                row.sync_hover(None)
            return False

        if event.type() in (
            QEvent.Type.Show,
            QEvent.Type.PolishRequest,
        ):
            _keep_markup_hover_cleared(menu)
            return False

        return False





class _HighlightColorPicker(QWidget):

    color_selected = pyqtSignal(str)

    more_requested = pyqtSignal()



    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        preset_order: Sequence[str] = HIGHLIGHT_PRESET_ORDER,
        icon_for: Callable[[str], QIcon] = color_circle_icon,
        light_tooltips: bool = True,
    ) -> None:

        super().__init__(parent)

        self.setAutoFillBackground(False)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setStyleSheet("background-color: transparent;")

        layout = QHBoxLayout(self)

        layout.setContentsMargins(10, 6, 10, 6)

        layout.setSpacing(6)



        for color_id in preset_order:

            button = QToolButton()

            button.setIcon(icon_for(color_id, size=16))

            button.setIconSize(QSize(16, 16))

            button.setFixedSize(24, 24)

            button.setAutoRaise(False)

            button.setStyleSheet(_COLOR_PICKER_TOOL_BUTTON_STYLE)

            button.setToolTip(_preset_tooltip(color_id, light=light_tooltips))

            button.setCursor(Qt.CursorShape.PointingHandCursor)

            button.clicked.connect(

                lambda _checked=False, cid=color_id: self.color_selected.emit(cid)

            )

            layout.addWidget(button)



        more = QPushButton("더보기")

        more.setFlat(True)

        more.setCursor(Qt.CursorShape.PointingHandCursor)

        more.setStyleSheet(

            "QPushButton {"

            f"  color: {_MENU_ITEM_TEXT_COLOR};"

            "  font-size: 12px;"

            "  padding: 2px 6px;"

            "  background: transparent;"

            "  border: none;"

            "  border-radius: 3px;"

            "}"

            "QPushButton:hover {"

            "  color: #111111;"

            f"  background-color: {_MENU_ITEM_HOVER_BG};"

            "}"

        )

        more.clicked.connect(self.more_requested.emit)

        layout.addWidget(more)





class _HighlightSubmenuArrow(QLabel):

    def __init__(

        self,

        row: "_HighlightSplitMenuItem",

        parent: QWidget | None = None,

    ) -> None:

        super().__init__(parent)

        self._row = row

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.setFixedSize(18, 18)

        self.setCursor(Qt.CursorShape.ArrowCursor)

        self.setStyleSheet("background: transparent;")

        self.setPixmap(
            _submenu_arrow_icon().pixmap(_SUBMENU_ARROW_ICON_PX, _SUBMENU_ARROW_ICON_PX)
        )

    def enterEvent(self, event) -> None:

        self._row.show_color_submenu()

        super().enterEvent(event)

    def mousePressEvent(self, event) -> None:

        if event.button() == Qt.MouseButton.LeftButton:

            self._row.show_color_submenu()

            event.accept()

            return

        super().mousePressEvent(event)





class _HighlightColorIcon(QLabel):

    def __init__(

        self,

        icon: QIcon,

        row: "_HighlightSplitMenuItem",

        parent: QWidget | None = None,

    ) -> None:

        super().__init__(parent)

        self._row = row

        self.setFixedSize(16, 16)

        self.setPixmap(icon.pixmap(16, 16))

        self.setStyleSheet("background: transparent;")

        self.setCursor(Qt.CursorShape.ArrowCursor)

    def enterEvent(self, event) -> None:

        self._row.show_color_submenu()

        super().enterEvent(event)

    def mousePressEvent(self, event) -> None:

        if event.button() == Qt.MouseButton.LeftButton:

            self._row.apply_default.emit()

            event.accept()

            return

        super().mousePressEvent(event)





class _HighlightSplitMenuItem(QWidget):

    apply_default = pyqtSignal()

    def __init__(
        self,
        color_menu: QMenu,
        icon: QIcon,
        label: str,
        parent_menu: QMenu,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color_menu = color_menu
        self._parent_menu = parent_menu
        self.setObjectName("markupMenuRow")

        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setAutoFillBackground(False)

        self.setMinimumHeight(26)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._hovered = False
        # Always paint an opaque row; otherwise QMenu::item:selected shows through
        # as a false hover on the custom 형광펜/밑줄 rows.
        self.force_set_hovered(False)

        color_menu.aboutToShow.connect(lambda: self.force_set_hovered(True))

        color_menu.aboutToHide.connect(self._sync_hover_from_cursor)



        layout = QHBoxLayout(self)

        layout.setContentsMargins(12, 4, 8, 4)

        layout.setSpacing(6)



        text_label = QLabel(label)

        text_label.setStyleSheet(

            f"color: {_MENU_ITEM_TEXT_COLOR}; font-size: 12px; background: transparent;"

        )

        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(text_label)

        layout.addStretch(1)

        self._color_icon = _HighlightColorIcon(icon, self, self)
        layout.addWidget(self._color_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addSpacing(2)

        self._arrow = _HighlightSubmenuArrow(self, self)
        layout.addWidget(self._arrow, 0, Qt.AlignmentFlag.AlignVCenter)

    def showEvent(self, event) -> None:
        self.force_set_hovered(False)
        self._parent_menu.setActiveAction(None)
        super().showEvent(event)

    def show_color_submenu(self) -> None:
        if self._color_menu.isVisible():
            return
        if self._hover_blocked():
            return
        self.force_set_hovered(True)
        anchor = self._arrow.mapToGlobal(QPoint(self._arrow.width(), 0))
        self._color_menu.popup(anchor)

    def _hover_blocked(self) -> bool:
        return bool(getattr(self._parent_menu, "_block_markup_hover", False))

    def _is_under_cursor(self, global_pos: QPoint) -> bool:
        local = self.mapFromGlobal(global_pos)
        return self.rect().contains(local)

    def _sync_hover_from_cursor(self) -> None:
        if self._color_menu.isVisible():
            self.force_set_hovered(True)
            return
        self.sync_hover(QCursor.pos())

    def sync_hover(self, global_pos: QPoint | None) -> None:
        if self._color_menu.isVisible():
            self.force_set_hovered(True)
            return
        if global_pos is None or self._hover_blocked():
            self.force_set_hovered(False)
            return
        self.force_set_hovered(self._is_under_cursor(global_pos))

    def _row_style(self, background: str) -> str:
        return (
            "QWidget#markupMenuRow {"
            f"  background-color: {background};"
            "  margin-top: -4px;"
            "  margin-bottom: -4px;"
            "  margin-left: -12px;"
            "  margin-right: -24px;"
            "}"
        )

    def force_set_hovered(self, hovered: bool) -> None:
        """Apply hover chrome even when the boolean state is unchanged."""
        self._hovered = hovered
        if hovered:
            self.setStyleSheet(self._row_style(_MENU_ITEM_HOVER_BG))
        else:
            self.setStyleSheet(self._row_style(_MENU_ITEM_NORMAL_BG))

    def set_hovered(self, hovered: bool) -> None:
        if self._hovered == hovered:
            return
        self.force_set_hovered(hovered)

    def enterEvent(self, event) -> None:
        if self._hover_blocked():
            self._parent_menu.setActiveAction(None)
            self.force_set_hovered(False)
        else:
            self.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._color_menu.isVisible():
            super().leaveEvent(event)
            return
        self.force_set_hovered(False)
        super().leaveEvent(event)



    def mousePressEvent(self, event) -> None:

        if event.button() == Qt.MouseButton.LeftButton:

            if self._arrow.geometry().contains(event.pos()):

                self._arrow.mousePressEvent(event)

                return

            if self._color_icon.geometry().contains(event.pos()):

                self._color_icon.mousePressEvent(event)

                return

            self.apply_default.emit()

            event.accept()

            return

        super().mousePressEvent(event)





def _preset_tooltip(color_id: str, *, light: bool = True) -> str:

    if light:
        labels = {
            "gray": "연한 회색",
            "yellow": "연한 노랑",
            "red": "연한 빨강",
            "blue": "연한 파랑",
            "green": "연한 초록",
        }
    else:
        labels = {
            "gray": "회색",
            "yellow": "노랑",
            "red": "빨강",
            "blue": "파랑",
            "green": "초록",
        }

    return labels.get(color_id, color_id)





def _add_colored_markup_menu_row(
    menu: QMenu,
    *,
    label: str,
    color_icon: QIcon,
    on_apply_default: Callable[[], None],
    on_color_selected: Callable[[str], None],
    on_more_colors: Callable[[], None],
    at_start: bool,
    preset_order: Sequence[str] = HIGHLIGHT_PRESET_ORDER,
    icon_for: Callable[[str], QIcon] = color_circle_icon,
    light_tooltips: bool = True,
) -> None:
    color_menu = QMenu(menu)
    color_menu.setStyleSheet(_HIGHLIGHT_COLOR_MENU_STYLE)

    picker_action = QWidgetAction(color_menu)
    picker = _HighlightColorPicker(
        color_menu,
        preset_order=preset_order,
        icon_for=icon_for,
        light_tooltips=light_tooltips,
    )

    def _pick_color(color_id: str) -> None:
        _dismiss_popup_menus(color_menu, menu)
        on_color_selected(color_id)

    def _pick_more() -> None:
        _dismiss_popup_menus(color_menu, menu)
        on_more_colors()

    picker.color_selected.connect(_pick_color)
    picker.more_requested.connect(_pick_more)
    picker_action.setDefaultWidget(picker)
    color_menu.addAction(picker_action)

    row_action = QWidgetAction(menu)
    row = _HighlightSplitMenuItem(color_menu, color_icon, label, menu)

    if not hasattr(menu, "_markup_rows"):
        menu._markup_rows = []
    menu._markup_rows.append(row)

    def _apply_default() -> None:
        _dismiss_popup_menus(color_menu, menu)
        on_apply_default()

    row.apply_default.connect(_apply_default)
    row_action.setDefaultWidget(row)

    def _sync_row_width() -> None:
        menu_width = menu.sizeHint().width()
        if menu_width > 0:
            row.setMinimumWidth(menu_width)

    menu.aboutToShow.connect(_sync_row_width)

    if at_start:
        first_action = menu.actions()[0] if menu.actions() else None
        if first_action is not None:
            menu.insertAction(first_action, row_action)
        else:
            menu.addAction(row_action)
    else:
        menu.addAction(row_action)


def add_text_highlight_menu_actions(
    menu: QMenu,
    *,
    on_apply_default: Callable[[], None],
    on_color_selected: Callable[[str], None],
    on_more_colors: Callable[[], None],
) -> None:
    _add_colored_markup_menu_row(
        menu,
        label="형광펜",
        color_icon=preferred_highlight_icon(),
        on_apply_default=on_apply_default,
        on_color_selected=on_color_selected,
        on_more_colors=on_more_colors,
        at_start=True,
    )


def add_text_underline_menu_actions(
    menu: QMenu,
    *,
    on_apply_default: Callable[[], None],
    on_color_selected: Callable[[str], None],
    on_more_colors: Callable[[], None],
) -> None:
    _add_colored_markup_menu_row(
        menu,
        label="밑줄",
        color_icon=preferred_underline_icon(),
        on_apply_default=on_apply_default,
        on_color_selected=on_color_selected,
        on_more_colors=on_more_colors,
        at_start=False,
        preset_order=UNDERLINE_PRESET_ORDER,
        icon_for=underline_color_circle_icon,
        light_tooltips=False,
    )





def build_text_selection_context_menu(
    parent: QWidget,
    *,
    on_apply_default_highlight: Callable[[], None],
    on_color_selected: Callable[[str], None],
    on_more_colors: Callable[[], None],
    on_apply_default_underline: Callable[[], None],
    on_underline_color_selected: Callable[[str], None],
    on_more_underline_colors: Callable[[], None],
    on_copy,
    on_remove_highlight: Callable[[], None] | None = None,
    show_remove_highlight: bool = False,
    on_remove_underline: Callable[[], None] | None = None,
    show_remove_underline: bool = False,
    show_continue_selection: bool = False,
    on_continue_selection: Callable[[], None] | None = None,
) -> QMenu:
    menu = QMenu(parent)
    menu.setStyleSheet(TEXT_SELECTION_MENU_STYLE)
    menu._markup_rows = []
    menu._block_markup_hover = True
    menu._hover_arm_pos = QCursor.pos()
    menu._markup_hover_filter = _MarkupMenuHoverFilter(menu)
    menu.installEventFilter(menu._markup_hover_filter)
    menu.aboutToShow.connect(lambda: _reset_markup_menu_hover(menu))
    add_text_highlight_menu_actions(
        menu,
        on_apply_default=on_apply_default_highlight,
        on_color_selected=on_color_selected,
        on_more_colors=on_more_colors,
    )
    if show_remove_highlight and on_remove_highlight is not None:
        remove_action = menu.addAction("형광펜 제거")
        remove_action.triggered.connect(on_remove_highlight)
    add_text_underline_menu_actions(
        menu,
        on_apply_default=on_apply_default_underline,
        on_color_selected=on_underline_color_selected,
        on_more_colors=on_more_underline_colors,
    )
    if show_remove_underline and on_remove_underline is not None:
        remove_action = menu.addAction("밑줄 제거")
        remove_action.triggered.connect(on_remove_underline)
    copy_action = menu.addAction("복사")
    copy_action.triggered.connect(on_copy)
    if show_continue_selection and on_continue_selection is not None:
        continue_action = menu.addAction("계속 선택하기")
        continue_action.triggered.connect(on_continue_selection)
    return menu


