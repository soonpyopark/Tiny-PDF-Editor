"""Context-menu UI for applying text highlights."""



from __future__ import annotations



from collections.abc import Callable



from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QSize, pyqtSignal

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

    color_circle_icon,

    preferred_highlight_icon,

)



_MENU_ITEM_TEXT_COLOR = "#333333"

_MENU_ITEM_HOVER_BG = "#ebebeb"



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





class _HighlightRowHoverFilter(QObject):

    """Keep highlight row hover while pointer is on the row or its color submenu."""



    def __init__(

        self,

        menu: QMenu,

        color_menu: QMenu,

        row: "_HighlightSplitMenuItem",

    ) -> None:

        super().__init__(menu)

        self._menu = menu

        self._color_menu = color_menu

        self._row = row

        menu.setMouseTracking(True)

        color_menu.setMouseTracking(True)

        color_menu.aboutToShow.connect(lambda: self._row.set_hovered(True))

        color_menu.aboutToHide.connect(self._sync_from_cursor)



    def _mouse_global_pos(self, event: QEvent) -> QPoint | None:

        if isinstance(event, QMouseEvent):

            return event.globalPosition().toPoint()

        return None



    def _is_over_row(self, global_pos: QPoint) -> bool:

        local = self._row.mapFromGlobal(global_pos)

        return self._row.rect().contains(local)



    def _sync_from_cursor(self) -> None:

        self._sync_hover(QCursor.pos())



    def _sync_hover(self, global_pos: QPoint) -> None:

        if self._color_menu.isVisible():

            self._row.set_hovered(True)

            return

        self._row.set_hovered(self._is_over_row(global_pos))



    def eventFilter(self, watched: QObject, event: QEvent) -> bool:

        if watched is self._menu:

            if event.type() == QEvent.Type.Leave:

                if not self._color_menu.isVisible():

                    self._row.set_hovered(False)

                return False

            if event.type() == QEvent.Type.MouseMove:

                global_pos = self._mouse_global_pos(event)

                if global_pos is not None:

                    self._sync_hover(global_pos)

            return False



        if watched is self._color_menu:

            if event.type() in (

                QEvent.Type.MouseMove,

                QEvent.Type.Enter,

            ):

                self._row.set_hovered(True)

            elif event.type() == QEvent.Type.Leave:

                self._sync_from_cursor()

            return False



        return False





class _HighlightColorPicker(QWidget):

    color_selected = pyqtSignal(str)

    more_requested = pyqtSignal()



    def __init__(self, parent: QWidget | None = None) -> None:

        super().__init__(parent)

        self.setAutoFillBackground(False)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setStyleSheet("background-color: transparent;")

        layout = QHBoxLayout(self)

        layout.setContentsMargins(10, 6, 10, 6)

        layout.setSpacing(6)



        for color_id in HIGHLIGHT_PRESET_ORDER:

            button = QToolButton()

            button.setIcon(color_circle_icon(color_id, size=16))

            button.setIconSize(QSize(16, 16))

            button.setFixedSize(24, 24)

            button.setAutoRaise(False)

            button.setStyleSheet(_COLOR_PICKER_TOOL_BUTTON_STYLE)

            button.setToolTip(_preset_tooltip(color_id))

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

        submenu: QMenu,

        row: "_HighlightSplitMenuItem",

        parent: QWidget | None = None,

    ) -> None:

        super().__init__(parent)

        self._submenu = submenu

        self._row = row

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.setFixedSize(18, 18)

        self.setCursor(Qt.CursorShape.ArrowCursor)

        self.setStyleSheet("background: transparent;")

        self.setPixmap(
            _submenu_arrow_icon().pixmap(_SUBMENU_ARROW_ICON_PX, _SUBMENU_ARROW_ICON_PX)
        )



    def _show_submenu(self) -> None:

        if self._submenu.isVisible():

            return

        self._row.set_hovered(True)

        anchor = self.mapToGlobal(QPoint(self.width(), 0))

        self._submenu.popup(anchor)



    def enterEvent(self, event) -> None:

        self._show_submenu()

        super().enterEvent(event)



    def mousePressEvent(self, event) -> None:

        if event.button() == Qt.MouseButton.LeftButton:

            self._show_submenu()

            event.accept()

            return

        super().mousePressEvent(event)





class _HighlightSplitMenuItem(QWidget):

    apply_default = pyqtSignal()



    def __init__(self, color_menu: QMenu, icon: QIcon, parent: QWidget | None = None) -> None:

        super().__init__(parent)

        self._color_menu = color_menu

        self.setObjectName("highlightMenuRow")

        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setAutoFillBackground(True)

        self.setMinimumHeight(26)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._hovered = False

        self.set_hovered(False)



        layout = QHBoxLayout(self)

        layout.setContentsMargins(12, 4, 8, 4)

        layout.setSpacing(6)



        text_label = QLabel("하이라이트")

        text_label.setStyleSheet(

            f"color: {_MENU_ITEM_TEXT_COLOR}; font-size: 12px; background: transparent;"

        )

        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(text_label)



        icon_label = QLabel()

        icon_label.setFixedSize(16, 16)

        icon_label.setPixmap(icon.pixmap(16, 16))

        icon_label.setStyleSheet("background: transparent;")

        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(icon_label)



        layout.addStretch(1)



        self._arrow = _HighlightSubmenuArrow(color_menu, self, self)

        layout.addWidget(self._arrow)



    def set_hovered(self, hovered: bool) -> None:

        if self._hovered == hovered:

            return

        self._hovered = hovered

        if hovered:

            self.setStyleSheet(

                f"QWidget#highlightMenuRow {{ background-color: {_MENU_ITEM_HOVER_BG}; }}"

            )

        else:

            self.setStyleSheet(

                "QWidget#highlightMenuRow { background-color: transparent; }"

            )



    def enterEvent(self, event) -> None:

        self.set_hovered(True)

        super().enterEvent(event)



    def leaveEvent(self, event) -> None:

        if self._color_menu.isVisible():

            super().leaveEvent(event)

            return

        self.set_hovered(False)

        super().leaveEvent(event)



    def mousePressEvent(self, event) -> None:

        if event.button() == Qt.MouseButton.LeftButton:

            if self._arrow.geometry().contains(event.pos()):

                self._arrow.mousePressEvent(event)

                return

            self.apply_default.emit()

            event.accept()

            return

        super().mousePressEvent(event)





def _preset_tooltip(color_id: str) -> str:

    labels = {

        "gray": "연한 회색",

        "yellow": "연한 노랑",

        "red": "연한 빨강",

        "blue": "연한 파랑",

        "green": "연한 초록",

    }

    return labels.get(color_id, color_id)





def add_text_highlight_menu_actions(

    menu: QMenu,

    *,

    on_apply_default: Callable[[], None],

    on_color_selected: Callable[[str], None],

    on_more_colors: Callable[[], None],

) -> None:

    """Insert split highlight row: click applies default color, > hover opens palette."""

    color_menu = QMenu(menu)

    color_menu.setStyleSheet(_HIGHLIGHT_COLOR_MENU_STYLE)



    picker_action = QWidgetAction(color_menu)

    picker = _HighlightColorPicker(color_menu)



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



    highlight_icon = preferred_highlight_icon()

    row_action = QWidgetAction(menu)

    row = _HighlightSplitMenuItem(color_menu, highlight_icon)



    def _apply_default() -> None:

        _dismiss_popup_menus(color_menu, menu)

        on_apply_default()



    row.apply_default.connect(_apply_default)

    row_action.setDefaultWidget(row)



    hover_filter = _HighlightRowHoverFilter(menu, color_menu, row)

    menu.installEventFilter(hover_filter)

    color_menu.installEventFilter(hover_filter)



    def _sync_row_width() -> None:

        menu_width = menu.sizeHint().width()

        if menu_width > 0:

            row.setMinimumWidth(menu_width)



    menu.aboutToShow.connect(_sync_row_width)



    first_action = menu.actions()[0] if menu.actions() else None

    if first_action is not None:

        menu.insertAction(first_action, row_action)

    else:

        menu.addAction(row_action)





def build_text_selection_context_menu(

    parent: QWidget,

    *,

    on_apply_default_highlight: Callable[[], None],

    on_color_selected: Callable[[str], None],

    on_more_colors: Callable[[], None],

    on_copy,

    on_remove_highlight: Callable[[], None] | None = None,

    show_remove_highlight: bool = False,

) -> QMenu:

    menu = QMenu(parent)

    menu.setStyleSheet(TEXT_SELECTION_MENU_STYLE)

    add_text_highlight_menu_actions(

        menu,

        on_apply_default=on_apply_default_highlight,

        on_color_selected=on_color_selected,

        on_more_colors=on_more_colors,

    )

    if show_remove_highlight and on_remove_highlight is not None:

        remove_action = menu.addAction("하이라이트 제거")

        remove_action.triggered.connect(on_remove_highlight)

    copy_action = menu.addAction("복사")

    copy_action.triggered.connect(on_copy)

    return menu


