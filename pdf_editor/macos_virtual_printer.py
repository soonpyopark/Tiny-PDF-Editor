"""Register Tiny as a macOS print target (PDF Services + optional CUPS)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from pdf_editor.version import APP_NAME

CUPS_QUEUE = "Tiny_PDF_Editor"
PDF_SERVICE_NAME = "Tiny PDF Editor"
BACKEND_NAME = "tiny-pdf-editor"


def is_macos() -> bool:
    return sys.platform == "darwin"


def support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def pdf_services_dir() -> Path:
    return Path.home() / "Library" / "PDF Services"


def frozen_app_bundle() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    # …/Tiny PDF Editor.app/Contents/MacOS/<exe>
    if exe.parent.name == "MacOS":
        return exe.parents[2]
    return None


def _as_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_open_helper() -> Path:
    folder = support_dir()
    folder.mkdir(parents=True, exist_ok=True)
    helper = folder / "open-printed-pdf.sh"
    bundle = frozen_app_bundle()
    if bundle is not None:
        body = (
            "#!/bin/bash\n"
            "exec /usr/bin/open -a "
            f"{_sh_quote(str(bundle))} "
            '"$1"\n'
        )
    else:
        python = str(Path(sys.executable).resolve())
        main_py = str(Path(__file__).resolve().parents[1] / "main.py")
        body = (
            "#!/bin/bash\n"
            f"exec {_sh_quote(python)} {_sh_quote(main_py)} "
            '"$1"\n'
        )
    helper.write_text(body, encoding="utf-8")
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return helper


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _remove_pdf_service_entries() -> None:
    dest_dir = pdf_services_dir()
    for name in (PDF_SERVICE_NAME, f"{PDF_SERVICE_NAME}.app"):
        path = dest_dir / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            subprocess.run(["rm", "-rf", str(path)], check=False)


def _install_pdf_service() -> None:
    dest_dir = pdf_services_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    _remove_pdf_service_entries()
    bundle = frozen_app_bundle()
    if bundle is not None:
        (dest_dir / PDF_SERVICE_NAME).symlink_to(bundle)
        return
    _install_dev_pdf_applet(dest_dir / f"{PDF_SERVICE_NAME}.app")


def _install_dev_pdf_applet(dest: Path) -> None:
    python = str(Path(sys.executable).resolve())
    main_py = str(Path(__file__).resolve().parents[1] / "main.py")
    source = support_dir() / "pdf-service-open.applescript"
    support_dir().mkdir(parents=True, exist_ok=True)
    source.write_text(
        "on open theDocs\n"
        "  repeat with d in theDocs\n"
        "    set p to POSIX path of d\n"
        "    do shell script quoted form of "
        f"{_as_string(python)}"
        " & \" \" & quoted form of "
        f"{_as_string(main_py)}"
        " & \" \" & quoted form of p\n"
        "  end repeat\n"
        "end open\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["osacompile", "-o", str(dest), str(source)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise OSError(completed.stderr.strip() or "PDF 서비스 애플릿을 만들지 못했습니다.")
    icns = Path(__file__).resolve().parent / "branding" / "app_icon.icns"
    applet_icns = dest / "Contents" / "Resources" / "applet.icns"
    if icns.is_file() and applet_icns.parent.is_dir():
        shutil.copy2(icns, applet_icns)


def _remove_pdf_service() -> None:
    _remove_pdf_service_entries()


def pdf_service_installed() -> bool:
    dest_dir = pdf_services_dir()
    link = dest_dir / PDF_SERVICE_NAME
    applet = dest_dir / f"{PDF_SERVICE_NAME}.app"
    return link.exists() or applet.exists()


def cups_printer_installed() -> bool:
    completed = subprocess.run(
        ["lpstat", "-p", CUPS_QUEUE],
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def printer_is_installed() -> bool:
    return pdf_service_installed() or cups_printer_installed()


def _backend_source() -> Path:
    path = support_dir() / "tiny-pdf-editor-backend.sh"
    support_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/bash\n"
        "if [ $# -eq 0 ]; then\n"
        '  echo "file tiny-pdf-editor \\"Tiny PDF Editor\\" \\"Tiny PDF Editor\\""\n'
        "  exit 0\n"
        "fi\n"
        'user="$2"\n'
        'if [ -z "$user" ]; then user="$(id -un)"; fi\n'
        'home=$(eval echo "~$user")\n'
        'mkdir -p "$home/Downloads"\n'
        'stamp=$(date +%y%m%d_%H%M%S)\n'
        'dest="$home/Downloads/Tiny 인쇄 ${stamp}.pdf"\n'
        'if [ -n "$6" ] && [ -f "$6" ]; then cp "$6" "$dest"; else cat > "$dest"; fi\n'
        f'helper="$home/Library/Application Support/{APP_NAME}/open-printed-pdf.sh"\n'
        'if [ -x "$helper" ]; then\n'
        '  if [ "$(id -u)" -eq 0 ]; then sudo -u "$user" "$helper" "$dest"; else "$helper" "$dest"; fi\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _try_lpadmin_user() -> bool:
    completed = subprocess.run(
        [
            "lpadmin",
            "-p",
            CUPS_QUEUE,
            "-D",
            APP_NAME,
            "-E",
            "-v",
            f"{BACKEND_NAME}:/",
            "-m",
            "raw",
        ],
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def _install_cups_with_admin() -> None:
    backend = _backend_source()
    script = support_dir() / "install-cups-printer.sh"
    dest_backend = f"/usr/libexec/cups/backend/{BACKEND_NAME}"
    script.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        f"cp {_sh_quote(str(backend))} {_sh_quote(dest_backend)}\n"
        f"chown root:wheel {_sh_quote(dest_backend)}\n"
        f"chmod 700 {_sh_quote(dest_backend)}\n"
        f"lpadmin -p {CUPS_QUEUE} -D {_sh_quote(APP_NAME)} -E "
        f"-v {BACKEND_NAME}:/ -m raw\n"
        f"cupsenable {CUPS_QUEUE} || true\n"
        f"accept {CUPS_QUEUE} || true\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    completed = subprocess.run(
        [
            "osascript",
            "-e",
            "do shell script quoted form of "
            f"{_as_string(str(script))} "
            "with administrator privileges",
        ],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise OSError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or "CUPS 프린터 등록에 관리자 권한이 필요합니다."
        )


def _remove_cups_with_admin() -> None:
    script = support_dir() / "remove-cups-printer.sh"
    support_dir().mkdir(parents=True, exist_ok=True)
    dest_backend = f"/usr/libexec/cups/backend/{BACKEND_NAME}"
    script.write_text(
        "#!/bin/bash\n"
        f"lpadmin -x {CUPS_QUEUE} || true\n"
        f"rm -f {_sh_quote(dest_backend)}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    subprocess.run(
        [
            "osascript",
            "-e",
            "do shell script quoted form of "
            f"{_as_string(str(script))} "
            "with administrator privileges",
        ],
        capture_output=True,
        text=True,
    )


def repair_pdf_service() -> None:
    """Keep PDF Services pointing at the current .app, not an old Contents path."""
    if not is_macos():
        return
    _write_open_helper()
    _install_pdf_service()


def install_virtual_printer(*, with_cups: bool = False) -> None:
    if not is_macos():
        raise OSError("macOS에서만 사용할 수 있습니다.")
    _write_open_helper()
    _install_pdf_service()
    if not with_cups:
        return
    if cups_printer_installed() or _try_lpadmin_user():
        return
    try:
        _install_cups_with_admin()
    except OSError:
        if pdf_service_installed():
            return
        raise


def uninstall_virtual_printer() -> None:
    if not is_macos():
        return
    _remove_pdf_service()
    if cups_printer_installed():
        if not _try_remove_cups_user():
            _remove_cups_with_admin()


def _try_remove_cups_user() -> bool:
    completed = subprocess.run(
        ["lpadmin", "-x", CUPS_QUEUE],
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def _looks_ephemeral(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    candidates = [
        Path("/tmp"),
        Path("/private/tmp"),
        Path("/var/folders"),
        Path("/private/var/folders"),
    ]
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        candidates.append(Path(tmpdir))
    for folder in candidates:
        try:
            if resolved.is_relative_to(folder.resolve()):
                return True
        except (OSError, ValueError):
            continue
    return False


def claim_incoming_pdf(path: str | Path) -> Path:
    """Copy a print-generated temp PDF into Downloads, matching Windows."""
    source = Path(path)
    if not source.is_file() or not _looks_ephemeral(source):
        return source
    from pdf_editor.virtual_printer import next_output_pdf

    dest = next_output_pdf()
    try:
        dest.write_bytes(source.read_bytes())
    except OSError:
        return source
    return dest if dest.is_file() else source
