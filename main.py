"""Tiny PDF Editor — entry point."""

import sys

from pdf_editor.qt_runtime import prepare_qt_dll_paths


def _run_printer_cli(argv: list[str]) -> None:
    """Register or remove the virtual printer without loading Qt.

    The MSI runs this during setup. Importing Qt there shows the QtCore
    DLL error dialog even when the installed app itself can start.
    """
    flags = {str(arg).lower() for arg in argv[1:]}
    install = "--install-printer" in flags
    uninstall = "--uninstall-printer" in flags
    if not install and not uninstall:
        return
    from pdf_editor.virtual_printer import (
        install_virtual_printer,
        is_macos,
        uninstall_virtual_printer,
    )

    if install:
        try:
            install_virtual_printer(with_cups=is_macos())
        except OSError:
            raise SystemExit(1) from None
    else:
        uninstall_virtual_printer()
    raise SystemExit(0)


if __name__ == "__main__":
    _run_printer_cli(sys.argv)

prepare_qt_dll_paths()

from pdf_editor.main_window import run

if __name__ == "__main__":
    run()
