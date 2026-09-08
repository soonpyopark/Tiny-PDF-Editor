"""Install a per-user virtual printer that writes PDF for Tiny to open."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pdf_editor.app_settings import default_downloads_folder
from pdf_editor.version import APP_NAME

PRINTER_NAME = "Tiny PDF Editor"
PRINTER_DRIVER = "Microsoft Print To PDF"
SPOOL_FILE_NAME = "tiny-print.pdf"
RUN_VALUE_NAME = "TinyPDFEditorPrintWatch"
WATCH_FLAG = "--print-watch"
INSTALL_FLAG = "--install-printer"
UNINSTALL_FLAG = "--uninstall-printer"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def supports_virtual_printer() -> bool:
    return is_windows() or is_macos()


def _local_app_data() -> Path:
    raw = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(raw)


def spool_dir() -> Path:
    return _local_app_data() / APP_NAME / "print-spool"


def spool_file() -> Path:
    return spool_dir() / SPOOL_FILE_NAME


def watch_lock_file() -> Path:
    return spool_dir() / "print-watch.lock"


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows() else 0


def _run_powershell(script: str) -> tuple[int, str]:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        text=True,
        timeout=90,
        creationflags=_creation_flags(),
    )
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    return completed.returncode, output


def printer_is_installed() -> bool:
    if is_macos():
        from pdf_editor.macos_virtual_printer import printer_is_installed as mac_installed

        return mac_installed()
    if not is_windows():
        return False
    script = (
        f"$p = Get-Printer -Name '{PRINTER_NAME}' -ErrorAction SilentlyContinue;"
        "if ($p) { 'YES' } else { 'NO' }"
    )
    code, output = _run_powershell(script)
    return code == 0 and "YES" in output


def exe_path() -> Path:
    return Path(sys.executable).resolve()


def watch_command() -> str:
    exe = exe_path()
    if getattr(sys, "frozen", False):
        return f'"{exe}" {WATCH_FLAG}'
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{exe}" "{main_py}" {WATCH_FLAG}'


def set_watch_at_logon(enabled: bool) -> None:
    if not is_windows():
        return
    import winreg

    key = winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, watch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def install_virtual_printer(*, with_cups: bool = False) -> None:
    if is_macos():
        from pdf_editor.macos_virtual_printer import (
            install_virtual_printer as mac_install,
        )

        mac_install(with_cups=with_cups)
        return
    if not is_windows():
        raise OSError("가상 프린터는 Windows와 macOS에서만 사용할 수 있습니다.")
    port = str(spool_file())
    spool_dir().mkdir(parents=True, exist_ok=True)
    script = f"""
$ErrorActionPreference = 'Stop'
$name = '{PRINTER_NAME}'
$driver = '{PRINTER_DRIVER}'
$port = '{port.replace("'", "''")}'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $port) | Out-Null
$existing = Get-Printer -Name $name -ErrorAction SilentlyContinue
if ($existing) {{
  Remove-Printer -Name $name
}}
$portObj = Get-PrinterPort -Name $port -ErrorAction SilentlyContinue
if (-not $portObj) {{
  Add-PrinterPort -Name $port
}}
Add-Printer -Name $name -DriverName $driver -PortName $port
"""
    code, output = _run_powershell(script)
    if code != 0:
        raise OSError(
            "가상 프린터를 설치하지 못했습니다.\n"
            "이 PC에 「Microsoft Print to PDF」 드라이버가 있어야 합니다.\n\n"
            + (output or "PowerShell 오류")
        )
    set_watch_at_logon(True)
    try:
        from pdf_editor.print_watch import launch_watch_if_needed

        launch_watch_if_needed()
    except Exception:
        pass


def uninstall_virtual_printer() -> None:
    if is_macos():
        from pdf_editor.macos_virtual_printer import (
            uninstall_virtual_printer as mac_uninstall,
        )

        mac_uninstall()
        return
    if not is_windows():
        return
    port = str(spool_file())
    script = f"""
$ErrorActionPreference = 'Continue'
$name = '{PRINTER_NAME}'
$port = '{port.replace("'", "''")}'
$existing = Get-Printer -Name $name -ErrorAction SilentlyContinue
if ($existing) {{
  Remove-Printer -Name $name
}}
$portObj = Get-PrinterPort -Name $port -ErrorAction SilentlyContinue
if ($portObj) {{
  Remove-PrinterPort -Name $port -ErrorAction SilentlyContinue
}}
"""
    _run_powershell(script)
    set_watch_at_logon(False)


def next_output_pdf() -> Path:
    stamp = datetime.now().strftime("%y%m%d_%H%M%S")
    folder = Path(default_downloads_folder())
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / f"Tiny 인쇄 {stamp}.pdf"
    index = 2
    while candidate.exists():
        candidate = folder / f"Tiny 인쇄 {stamp}_{index}.pdf"
        index += 1
    return candidate


def file_is_ready(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < 8:
        return False
    try:
        with path.open("rb+") as handle:
            header = handle.read(5)
        return header.startswith(b"%PDF-")
    except OSError:
        return False


def claim_spool_pdf() -> Path | None:
    source = spool_file()
    if not file_is_ready(source):
        return None
    dest = next_output_pdf()
    try:
        source.replace(dest)
    except OSError:
        try:
            dest.write_bytes(source.read_bytes())
            source.unlink(missing_ok=True)
        except OSError:
            return None
    return dest if dest.is_file() else None
