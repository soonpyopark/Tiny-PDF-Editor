"""Convert HWP/HWPX to PDF using installed Hancom Hangul (32-bit helper)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path

if sys.platform == "win32":
    import winreg
else:
    winreg = None  # type: ignore[assignment]

HWP_EXTENSIONS = {".hwp", ".hwpx"}

_GUIDANCE_NOT_INSTALLED = (
    "한컴 한글(한컴오피스)이 설치되어 있지 않습니다.\n\n"
    "HWP/HWPX 파일을 PDF로 변환하려면 한컴 한글이 필요합니다.\n"
    "한컴오피스를 설치한 뒤 다시 시도해 주세요."
)

_GUIDANCE_UNSUPPORTED_PLATFORM = (
    "HWP/HWPX 변환은 Windows에서만 지원됩니다.\n\n"
    "한컴 한글 자동 변환은 Windows용 Tiny PDF Editor에서 사용할 수 있습니다.\n"
    "macOS에서는 PDF 또는 이미지 파일을 열어 주세요."
)

_GUIDANCE_AUTOMATION = (
    "한컴 한글은 설치되어 있지만 자동 변환에 실패했습니다.\n\n"
    "다음을 확인한 뒤 다시 시도해 주세요.\n"
    "• 한컴 한글을 한 번 실행해 초기 설정을 완료했는지\n"
    "• 파일이 암호로 보호되어 있지 않은지\n"
    "• 다른 프로그램에서 해당 HWP 파일을 열고 있지 않은지"
)

ProgressFactory = Callable[[str], AbstractContextManager[None]]
_progress_factory: ProgressFactory | None = None


def set_conversion_progress_factory(factory: ProgressFactory | None) -> None:
    """Optional UI hook: ``factory(path)`` returns a context manager around conversion."""
    global _progress_factory
    _progress_factory = factory


@contextmanager
def _conversion_progress(path: str) -> Iterator[None]:
    if _progress_factory is None:
        with nullcontext():
            yield
        return
    with _progress_factory(path):
        yield


class HancomNotInstalledError(RuntimeError):
    """Hancom Hangul is not installed on this PC."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or _GUIDANCE_NOT_INSTALLED)


class HancomConvertError(RuntimeError):
    """HWP/HWPX conversion failed."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or _GUIDANCE_AUTOMATION)


def is_hwp_file(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.lower() in HWP_EXTENSIONS


def find_hwp_exe() -> Path | None:
    """Return path to Hwp.exe if Hancom Hangul appears installed."""
    if sys.platform != "win32" or winreg is None:
        return None

    path_values: list[str] = []
    for root, subkey, name in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\HNC\Shared", "Hnc Path130"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\HNC\Shared", "Hnc Path130"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\HNC\Shared", "Hnc Path120"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\HNC\Shared", "Hnc Path110"),
    ):
        value = _read_reg_string(root, subkey, name)
        if value:
            path_values.append(value)

    for root in path_values:
        for rel in (
            ("HOffice130", "Bin", "Hwp.exe"),
            ("HOffice120", "Bin", "Hwp.exe"),
            ("HOffice110", "Bin", "Hwp.exe"),
            ("Bin", "Hwp.exe"),
        ):
            candidate = Path(root).joinpath(*rel)
            if candidate.is_file():
                return candidate

    pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    for rel in (
        r"Hnc\Office 2024\HOffice130\Bin\Hwp.exe",
        r"HNC\Office 2024\HOffice130\Bin\Hwp.exe",
        r"Hnc\Office 2022\HOffice120\Bin\Hwp.exe",
        r"Hnc\Office 2020\HOffice110\Bin\Hwp.exe",
    ):
        candidate = Path(pf86) / rel
        if candidate.is_file():
            return candidate
    return None


def hancom_installed() -> bool:
    return find_hwp_exe() is not None


def _read_reg_string(root: int, subkey: str, name: str) -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, str) and value.strip() else None


def _vendor_dir() -> Path:
    return Path(__file__).resolve().parent / "vendor"


def _helper_exe() -> Path:
    return _vendor_dir() / "hwp_to_pdf_helper.exe"


def convert_hwp_to_pdf(
    source_path: str | os.PathLike[str],
    output_pdf: str | os.PathLike[str] | None = None,
    *,
    timeout_sec: float = 180.0,
) -> Path:
    """Convert an HWP/HWPX file to PDF. Returns the output PDF path."""
    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {source}")
    if not is_hwp_file(source):
        raise ValueError(f"HWP/HWPX 파일이 아닙니다: {source.suffix}")

    if sys.platform != "win32":
        raise HancomNotInstalledError(_GUIDANCE_UNSUPPORTED_PLATFORM)

    hwp_exe = find_hwp_exe()
    if hwp_exe is None:
        raise HancomNotInstalledError()

    helper = _helper_exe()
    if not helper.is_file():
        raise HancomConvertError(
            "HWP 변환 도우미를 찾을 수 없습니다.\n"
            "앱을 다시 설치하거나 배포판을 확인해 주세요."
        )

    if output_pdf is None:
        fd, tmp_name = tempfile.mkstemp(prefix="tiny_hwp_", suffix=".pdf")
        os.close(fd)
        output = Path(tmp_name)
    else:
        output = Path(output_pdf).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists():
        try:
            output.unlink()
        except OSError:
            pass

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    with _conversion_progress(str(source)):
        try:
            completed = subprocess.run(
                [str(helper), str(source), str(output), str(hwp_exe)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
                creationflags=creationflags,
                cwd=str(_vendor_dir()),
            )
        except subprocess.TimeoutExpired as exc:
            raise HancomConvertError(
                "HWP 변환 시간이 초과되었습니다.\n한컴 한글이 응답하는지 확인해 주세요."
            ) from exc

    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    code = completed.returncode

    if code == 2 or "HANCOM_NOT_FOUND" in stderr:
        raise HancomNotInstalledError()
    if code == 3 or "HANCOM_AUTOMATION_UNAVAILABLE" in stderr:
        raise HancomConvertError(_GUIDANCE_AUTOMATION)
    if code != 0 or not output.is_file() or output.stat().st_size <= 0:
        detail = stderr or stdout or f"exit code {code}"
        raise HancomConvertError(f"{_GUIDANCE_AUTOMATION}\n\n(상세: {detail})")
    return output


def convert_hwp_to_temp_pdf(source_path: str | os.PathLike[str]) -> Path:
    """Convert to a temporary PDF path (caller should delete when done)."""
    return convert_hwp_to_pdf(source_path, output_pdf=None)
