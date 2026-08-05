"""UI progress for Hancom HWP/HWPX → PDF conversion."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QProgressDialog, QWidget


def _visible_progress_dialog() -> QProgressDialog | None:
    app = QApplication.instance()
    if app is None:
        return None
    for widget in app.topLevelWidgets():
        if isinstance(widget, QProgressDialog) and widget.isVisible():
            return widget
    return None


def _active_parent() -> QWidget | None:
    app = QApplication.instance()
    if app is None:
        return None
    return app.activeWindow()


@contextmanager
def hwp_conversion_progress(path: str | os.PathLike[str]) -> Iterator[None]:
    """Show or update a busy dialog while Hangul converts a document."""
    name = Path(path).name
    message = f"한글 문서 변환 중…\n{name}"

    existing = _visible_progress_dialog()
    if existing is not None:
        previous = existing.labelText()
        existing.setLabelText(message)
        QApplication.processEvents()
        try:
            yield
        finally:
            try:
                existing.setLabelText(previous)
            except RuntimeError:
                pass
            QApplication.processEvents()
        return

    parent = _active_parent()
    dialog = QProgressDialog(message, None, 0, 0, parent)
    dialog.setWindowTitle("한글 문서 변환")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setCancelButton(None)
    dialog.setMinimumWidth(320)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.show()
    QApplication.processEvents()
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()
        dialog.close()
        dialog.deleteLater()
        QApplication.processEvents()


def register_hwp_conversion_progress() -> None:
    """Wire UI progress into the HWP conversion module."""
    from pdf_editor.hwp_convert import set_conversion_progress_factory

    set_conversion_progress_factory(hwp_conversion_progress)
