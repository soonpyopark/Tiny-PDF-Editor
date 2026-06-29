"""Functional checks for menu shortcut activation."""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication


def _action_keys(window) -> dict[str, str]:
    from PyQt6.QtGui import QAction

    mapping: dict[str, str] = {}
    for action in window.findChildren(QAction):
        keys = action.shortcuts() or ([action.shortcut()] if not action.shortcut().isEmpty() else [])
        portable = [
            seq.toString(QKeySequence.SequenceFormat.PortableText)
            for seq in keys
            if not seq.isEmpty()
        ]
        if not portable:
            continue
        label = action.text().replace("&", "").strip()
        mapping[label] = portable[0] if len(portable) == 1 else ",".join(portable)
    return mapping


def _shortcut_keys(window) -> set[str]:
    from PyQt6.QtGui import QShortcut

    keys: set[str] = set()
    for shortcut in window.findChildren(QShortcut):
        seq = shortcut.key()
        if seq.isEmpty():
            continue
        keys.add(seq.toString(QKeySequence.SequenceFormat.PortableText))
    return keys


def _send_shortcut(window, sequence) -> None:
    if isinstance(sequence, QKeySequence.StandardKey):
        seq = QKeySequence(sequence)
    else:
        seq = QKeySequence(sequence)
    window.activateWindow()
    window.raise_()
    QTest.keySequence(window, seq)
    QApplication.processEvents()


def main() -> int:
    app = QApplication(sys.argv)
    from pdf_editor.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()

    action_keys = _action_keys(window)
    extra_keys = _shortcut_keys(window)
    conflicts = set(action_keys.values()) & extra_keys
    # Redo lists both Ctrl+Y twice in portable form sometimes; compare normalized
    flat_action = set()
    for value in action_keys.values():
        flat_action.update(value.split(","))

    conflicts = flat_action & extra_keys
    print("=== Action vs QShortcut conflicts ===")
    if conflicts:
        for key in sorted(conflicts):
            labels = [label for label, val in action_keys.items() if key in val.split(",")]
            print(f"  CONFLICT {key}: menu actions {labels}")
    else:
        print("  (none)")

    tab = window._current_tab()
    assert tab is not None
    tab.thumbnails.list_widget.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()

    failures: list[str] = []

    # Undo: delete one page then restore with Ctrl+Z
    tab.document.insert_blank_page_at(0)
    tab.document.insert_blank_page_at(1)
    tab.refresh_all()
    count_before = tab.document.page_count
    tab._on_delete([0])
    if tab.document.page_count != count_before - 1:
        failures.append("setup delete failed")
    else:
        _send_shortcut(window, QKeySequence.StandardKey.Undo)
        if tab.document.page_count != count_before:
            failures.append("Ctrl+Z undo did not restore deleted page")
        else:
            print("[OK] Ctrl+Z undo")

    # Redo
    _send_shortcut(window, QKeySequence.StandardKey.Redo)
    if tab.document.page_count != count_before - 1:
        failures.append("Ctrl+Y redo did not re-delete page")
    else:
        print("[OK] Ctrl+Y redo")

    # Copy / paste
    tab.refresh_all(keep_index=0)
    tab.thumbnails.list_widget.setFocus(Qt.FocusReason.OtherFocusReason)
    tab.thumbnails.list_widget.clear_all_selection()
    tab.thumbnails.list_widget.item(0).setSelected(True)
    app.processEvents()
    count_before = tab.document.page_count
    _send_shortcut(window, QKeySequence.StandardKey.Copy)
    _send_shortcut(window, QKeySequence.StandardKey.Paste)
    if tab.document.page_count != count_before + 1:
        failures.append("Ctrl+C/Ctrl+V copy/paste did not add a page")
    else:
        print("[OK] Ctrl+C / Ctrl+V copy/paste")

    # Delete selected page
    last_row = tab.document.page_count - 1
    tab.thumbnails.set_current_index(last_row)
    tab.thumbnails.list_widget.item(last_row).setSelected(True)
    tab.thumbnails.list_widget.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()
    count_before = tab.document.page_count
    _send_shortcut(window, QKeySequence.StandardKey.Delete)
    if tab.document.page_count != count_before - 1:
        failures.append("Delete key did not remove selected page")
    else:
        print("[OK] Delete")

    # Find focuses search bar
    _send_shortcut(window, QKeySequence.StandardKey.Find)
    if not window._search_bar.search_edit.hasFocus():
        failures.append("Ctrl+F did not focus search bar")
    else:
        print("[OK] Ctrl+F find")

    print("\n=== Registered menu shortcuts ===")
    for label in sorted(action_keys):
        print(f"  {label}: {action_keys[label]}")

    print("\n=== Result ===")
    if failures or conflicts:
        for msg in failures:
            print(f"  FAIL: {msg}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
