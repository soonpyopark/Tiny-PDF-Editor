"""Tiny PDF Editor — entry point."""

from __future__ import annotations

import sys


def _run_printer_cli(argv: list[str]) -> int:
    """Register or remove the virtual printer without loading Qt.

    The MSI runs this during setup. Importing Qt there shows the QtCore
    DLL error dialog even when the installed app itself can start.
    """
    from pdf_editor.virtual_printer import (
        install_virtual_printer,
        is_macos,
        uninstall_virtual_printer,
    )

    flags = {str(arg).lower() for arg in argv[1:]}
    if "--install-printer" in flags:
        try:
            install_virtual_printer(with_cups=is_macos())
        except OSError:
            return 1
        return 0
    if "--uninstall-printer" in flags:
        uninstall_virtual_printer()
        return 0
    return -1


def _is_printer_cli(argv: list[str]) -> bool:
    flags = {str(arg).lower() for arg in argv[1:]}
    return "--install-printer" in flags or "--uninstall-printer" in flags


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv if argv is None else argv)
    # Printer setup must exit before any Qt import or DLL preload.
    if _is_printer_cli(args):
        raise SystemExit(_run_printer_cli(args))

    from pdf_editor.qt_runtime import prepare_qt_dll_paths

    prepare_qt_dll_paths()

    from pdf_editor.main_window import run

    run(args)


if __name__ == "__main__":
    main()
