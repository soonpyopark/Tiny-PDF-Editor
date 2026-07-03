"""Dialogs and widgets for PDF password entry."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

_ICON_PX = 16
_ICON_COLOR = QColor("#666666")


def _blank_pixmap() -> QPixmap:
    pixmap = QPixmap(_ICON_PX, _ICON_PX)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _icon_pen(width: float = 1.3) -> QPen:
    return QPen(
        _ICON_COLOR,
        width,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )


def _password_hidden_icon() -> QIcon:
    """Eye icon: click to show password."""
    pixmap = _blank_pixmap()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(_icon_pen())
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(2, 5, 12, 8)
    painter.setBrush(_ICON_COLOR)
    painter.drawEllipse(6, 7, 4, 4)
    painter.end()
    return QIcon(pixmap)


def _password_visible_icon() -> QIcon:
    """Eye with slash: click to hide password."""
    pixmap = _blank_pixmap()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(_icon_pen())
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(2, 5, 12, 8)
    painter.setPen(QPen(_ICON_COLOR, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(3, 13, 13, 3)
    painter.end()
    return QIcon(pixmap)


class PasswordLineEdit(QLineEdit):
    """Password field with a trailing visibility toggle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_visible = False
        self._toggle_action = QAction(self)
        self._toggle_action.setToolTip("비밀번호 표시")
        self._toggle_action.triggered.connect(self._toggle_password_visibility)
        self._update_toggle_icon()
        self.addAction(
            self._toggle_action,
            QLineEdit.ActionPosition.TrailingPosition,
        )

    def _toggle_password_visibility(self) -> None:
        self._password_visible = not self._password_visible
        self.setEchoMode(
            QLineEdit.EchoMode.Normal
            if self._password_visible
            else QLineEdit.EchoMode.Password
        )
        self._update_toggle_icon()

    def _update_toggle_icon(self) -> None:
        if self._password_visible:
            self._toggle_action.setIcon(_password_visible_icon())
            self._toggle_action.setToolTip("비밀번호 숨기기")
        else:
            self._toggle_action.setIcon(_password_hidden_icon())
            self._toggle_action.setToolTip("비밀번호 표시")


class SetPasswordDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PDF 비밀번호 설정")
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 12)

        hint = QLabel(
            "저장할 때 PDF 열기 비밀번호가 적용됩니다.\n"
            "소유자 비밀번호는 비워 두면 열기 비밀번호와 같게 설정됩니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(hint)

        form = QFormLayout()
        self._user_edit = PasswordLineEdit()
        form.addRow("열기 비밀번호:", self._user_edit)

        self._confirm_edit = PasswordLineEdit()
        form.addRow("비밀번호 확인:", self._confirm_edit)

        self._owner_edit = PasswordLineEdit()
        self._owner_edit.setPlaceholderText("선택 사항")
        form.addRow("소유자 비밀번호:", self._owner_edit)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("설정")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept_if_valid(self) -> None:
        user_password = self._user_edit.text()
        confirm = self._confirm_edit.text()
        if not user_password:
            self._show_error("열기 비밀번호를 입력하세요.")
            return
        if len(user_password) > 40:
            self._show_error("비밀번호는 40자 이하여야 합니다.")
            return
        if user_password != confirm:
            self._show_error("비밀번호 확인이 일치하지 않습니다.")
            return
        owner_password = self._owner_edit.text()
        if owner_password and len(owner_password) > 40:
            self._show_error("소유자 비밀번호는 40자 이하여야 합니다.")
            return
        self.accept()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "PDF 비밀번호", message)

    def passwords(self) -> tuple[str, str | None]:
        owner = self._owner_edit.text()
        return self._user_edit.text(), owner or None


class OpenPdfPasswordDialog(QDialog):
    """Prompt for the password of an encrypted PDF."""

    def __init__(
        self,
        path: str,
        parent: QWidget | None = None,
        *,
        wrong: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("PDF 비밀번호")
        self.setMinimumWidth(360)
        self._wrong = wrong
        self._path = path
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 12)

        name = os.path.basename(self._path)
        message = f"'{name}' 파일의 비밀번호를 입력하세요."
        if self._wrong:
            message = f"비밀번호가 올바르지 않습니다.\n\n{message}"

        prompt = QLabel(message)
        prompt.setWordWrap(True)
        root.addWidget(prompt)

        form = QFormLayout()
        self._password_edit = PasswordLineEdit()
        form.addRow("비밀번호:", self._password_edit)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._password_edit.returnPressed.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if not self._password_edit.text():
            QMessageBox.warning(self, "PDF 비밀번호", "비밀번호를 입력하세요.")
            return
        self.accept()

    def password(self) -> str:
        return self._password_edit.text()


def prompt_pdf_password(
    parent: QWidget | None,
    path: str,
    *,
    wrong: bool = False,
) -> str | None:
    dialog = OpenPdfPasswordDialog(path, parent, wrong=wrong)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.password()
