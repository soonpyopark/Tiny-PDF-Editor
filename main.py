"""Tiny PDF Editor — entry point."""

from pdf_editor.qt_runtime import prepare_qt_dll_paths

prepare_qt_dll_paths()

from pdf_editor.main_window import run

if __name__ == "__main__":
    run()
