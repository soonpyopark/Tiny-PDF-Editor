"""Load guide URLs from HELP.txt in the application root."""

from __future__ import annotations

import sys
from pathlib import Path

HELP_FILE = "HELP.txt"

_DEFAULT_REDUCE_USAGE_GUIDE_URL = (
    "https://note4all.tistory.com/pages/Tiny-PDF-Editor-"
    "%EC%9A%A9%EB%9F%89-%EC%A4%84%EC%9D%B4%EA%B8%B0-%EC%82%AC%EC%9A%A9-%EB%B0%A9%EB%B2%95"
)

_SETTING_DEFAULTS: dict[str, str] = {
    "REDUCE_USAGE_GUIDE_URL": _DEFAULT_REDUCE_USAGE_GUIDE_URL,
}


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _parse_setting_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key, value


def _load_help_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        parsed = _parse_setting_line(line)
        if parsed is not None:
            values[parsed[0]] = parsed[1]
    return values


def _resolve_settings() -> dict[str, str]:
    file_values = _load_help_file(_app_root() / HELP_FILE)
    resolved: dict[str, str] = {}
    for key, default in _SETTING_DEFAULTS.items():
        resolved[key] = file_values.get(key, "").strip() or default
    return resolved


_settings = _resolve_settings()

REDUCE_USAGE_GUIDE_URL = _settings["REDUCE_USAGE_GUIDE_URL"]
