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


def _parent_is_msiexec() -> bool:
    """True when msiexec.exe is found up the process parent chain."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    th32cs_snapprocess = 0x00000002
    invalid_handle = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    snapshot = kernel32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if not snapshot or snapshot == invalid_handle:
        return False

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    parents: dict[int, tuple[int, str]] = {}
    try:
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            parents[int(entry.th32ProcessID)] = (
                int(entry.th32ParentProcessID),
                entry.szExeFile.lower(),
            )
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    pid = int(kernel32.GetCurrentProcessId())
    seen: set[int] = set()
    # Walk a few ancestors so msiexec → cmd/powershell → exe still matches.
    for _ in range(8):
        if pid in seen:
            break
        seen.add(pid)
        info = parents.get(pid)
        if info is None:
            break
        parent_pid, name = info
        if name.endswith("msiexec.exe"):
            return True
        if parent_pid <= 0 or parent_pid == pid:
            break
        pid = parent_pid
    return False


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv if argv is None else argv)
    # Printer setup must exit before any Qt import or DLL preload.
    if _is_printer_cli(args):
        raise SystemExit(_run_printer_cli(args))

    # Defense in depth: never load Qt if somehow started by Windows Installer.
    # Printer setup is done on first app launch, not from MSI custom actions.
    if _parent_is_msiexec():
        raise SystemExit(0)

    from pdf_editor.qt_runtime import prepare_qt_dll_paths

    prepare_qt_dll_paths()

    from pdf_editor.main_window import run

    run(args)


if __name__ == "__main__":
    main()
