"""Register Tiny PDF Editor as a PDF handler on Windows (HKCU, no admin)."""

from __future__ import annotations

import os
import sys
import winreg
from pathlib import Path

from pdf_editor.resources import installed_pdf_file_icon_path
from pdf_editor.version import APP_NAME

_CAPABILITIES_KEY = r"Software\TinyPDFEditor\Capabilities"
_REGISTERED_APPS_KEY = r"Software\RegisteredApplications"
_REGISTERED_APPS_VALUE = "Tiny PDF Editor"
_PROGID = "TinyPDFEditor.pdf"
_PDF_EXTENSION = ".pdf"
# IThumbnailProvider ShellEx — Windows uses this for large-icon page previews.
_THUMBNAIL_SHELLEX = "{e357fccd-a995-4576-b01f-234630154e96}"


def is_windows() -> bool:
    return sys.platform == "win32"


def exe_path() -> Path:
    return Path(sys.executable).resolve()


def _exe_name() -> str:
    return exe_path().name


def _applications_key() -> str:
    return rf"Software\Classes\Applications\{_exe_name()}"


def _open_command() -> str:
    return f'"{exe_path()}" "%1"'


def _default_icon_value() -> str:
    icon_path = installed_pdf_file_icon_path()
    if icon_path is not None:
        return f"{icon_path},0"
    return f"{exe_path()},0"


def _set_value(root: int, subkey: str, name: str, value: str) -> None:
    key = winreg.CreateKeyEx(root, subkey, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    finally:
        winreg.CloseKey(key)


def _delete_tree(root: int, subkey: str) -> None:
    if not is_windows():
        return
    try:
        import ctypes

        result = ctypes.windll.advapi32.RegDeleteTreeW(root, subkey)
        if result != 0:
            winreg.DeleteKey(root, subkey)
    except OSError:
        pass


def _delete_value(root: int, subkey: str, name: str) -> None:
    try:
        key = winreg.OpenKey(root, subkey, 0, winreg.KEY_SET_VALUE)
    except OSError:
        return
    try:
        winreg.DeleteValue(key, name)
    except OSError:
        pass
    finally:
        winreg.CloseKey(key)


def _notify_assoc_changed() -> None:
    if not is_windows():
        return
    try:
        import ctypes

        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except OSError:
        pass


def _disable_pdf_thumbnails(root: int) -> None:
    """Prefer DefaultIcon over first-page live thumbnails in Explorer."""
    for base in (
        rf"Software\Classes\{_PDF_EXTENSION}",
        rf"Software\Classes\SystemFileAssociations\{_PDF_EXTENSION}",
    ):
        _set_value(root, rf"{base}\ShellEx\{_THUMBNAIL_SHELLEX}", "", "")


def _clear_pdf_thumbnail_overrides(root: int) -> None:
    for base in (
        rf"Software\Classes\{_PDF_EXTENSION}",
        rf"Software\Classes\SystemFileAssociations\{_PDF_EXTENSION}",
    ):
        _delete_tree(root, rf"{base}\ShellEx\{_THUMBNAIL_SHELLEX}")


def is_pdf_association_registered() -> bool:
    if not is_windows():
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            rf"{_applications_key()}\shell\open\command",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "")
            return os.path.normcase(value) == os.path.normcase(_open_command())
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def register_pdf_association() -> None:
    if not is_windows():
        raise OSError("Windows에서만 사용할 수 있습니다.")

    command = _open_command()
    app_key = _applications_key()
    icon = _default_icon_value()
    root = winreg.HKEY_CURRENT_USER

    _set_value(root, app_key, "", APP_NAME)
    _set_value(root, app_key, "FriendlyAppName", APP_NAME)
    _set_value(root, app_key, "AppUserModelID", "TinyPDFEditor.TinyPDFEditor.1")
    _set_value(root, rf"{app_key}\shell\open\command", "", command)
    _set_value(root, rf"{app_key}\SupportedTypes\.pdf", "", "")
    _set_value(root, rf"{app_key}\DefaultIcon", "", icon)

    _set_value(root, _CAPABILITIES_KEY, "ApplicationName", APP_NAME)
    _set_value(root, _CAPABILITIES_KEY, "ApplicationDescription", f"{APP_NAME} PDF editor")
    _set_value(root, _CAPABILITIES_KEY, "ApplicationIcon", icon)
    _set_value(
        root,
        rf"{_CAPABILITIES_KEY}\FileAssociations",
        _PDF_EXTENSION,
        _PROGID,
    )
    _set_value(root, _REGISTERED_APPS_KEY, _REGISTERED_APPS_VALUE, _CAPABILITIES_KEY)

    _set_value(root, rf"Software\Classes\{_PROGID}", "", APP_NAME)
    _set_value(root, rf"Software\Classes\{_PROGID}\DefaultIcon", "", icon)
    _set_value(root, rf"Software\Classes\{_PROGID}\shell\open\command", "", command)

    # Claim .pdf and point its icon at our branding (used when we are the ProgID).
    _set_value(root, rf"Software\Classes\{_PDF_EXTENSION}", "", _PROGID)
    _set_value(root, rf"Software\Classes\{_PDF_EXTENSION}\DefaultIcon", "", icon)
    _set_value(
        root,
        rf"Software\Classes\{_PDF_EXTENSION}\OpenWithProgids",
        _PROGID,
        "",
    )

    _disable_pdf_thumbnails(root)
    _notify_assoc_changed()


def unregister_pdf_association() -> None:
    if not is_windows():
        raise OSError("Windows에서만 사용할 수 있습니다.")

    root = winreg.HKEY_CURRENT_USER
    _delete_value(root, rf"Software\Classes\{_PDF_EXTENSION}\OpenWithProgids", _PROGID)

    try:
        key = winreg.OpenKey(root, rf"Software\Classes\{_PDF_EXTENSION}")
        try:
            value, _ = winreg.QueryValueEx(key, "")
        finally:
            winreg.CloseKey(key)
        if value == _PROGID:
            _delete_value(root, rf"Software\Classes\{_PDF_EXTENSION}", "")
    except OSError:
        pass

    _delete_tree(root, rf"Software\Classes\{_PDF_EXTENSION}\DefaultIcon")
    _clear_pdf_thumbnail_overrides(root)
    _delete_tree(root, _applications_key())
    _delete_tree(root, rf"Software\Classes\{_PROGID}")
    _delete_value(root, _REGISTERED_APPS_KEY, _REGISTERED_APPS_VALUE)
    _delete_tree(root, _CAPABILITIES_KEY)
    _notify_assoc_changed()


def open_pdf_default_apps_settings() -> None:
    if not is_windows():
        return
    os.startfile("ms-settings:defaultapps")
