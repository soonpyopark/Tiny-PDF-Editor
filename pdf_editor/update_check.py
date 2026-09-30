"""Check for newer releases on GitHub (version + platform build stamp)."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QMessageBox, QWidget

from pdf_editor.version import APP_BUILD_STAMP, APP_NAME, __version__, version_label

GITHUB_REPO = "soonpyopark/Tiny-PDF-Editor"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?")
_BUILD_STAMP_RE = re.compile(r"(\d{6}_\d{6})")


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    current: str
    current_build_stamp: str | None = None
    latest: str | None = None
    latest_build_stamp: str | None = None
    release_updated_at: str | None = None
    release_url: str | None = None
    error: str | None = None
    # True when the latest release has at least one asset for this OS.
    platform_assets_found: bool = False

    @property
    def update_kind(self) -> str | None:
        return resolve_update_kind(self)

    @property
    def update_available(self) -> bool:
        return self.update_kind is not None


def _version_tuple(text: str) -> tuple[int, ...]:
    match = _VERSION_RE.search(text.strip())
    if not match:
        return (0,)
    parts = [int(part) for part in match.groups() if part is not None]
    return tuple(parts)


def _compare_versions(left: str, right: str) -> int:
    a = _version_tuple(left)
    b = _version_tuple(right)
    length = max(len(a), len(b))
    for index in range(length):
        la = a[index] if index < len(a) else 0
        rb = b[index] if index < len(b) else 0
        if la > rb:
            return 1
        if la < rb:
            return -1
    return 0


def parse_release_tag(tag_name: str) -> str | None:
    match = _VERSION_RE.search(tag_name or "")
    if not match:
        return None
    return ".".join(part for part in match.groups() if part is not None)


def parse_build_stamp(name: str) -> str | None:
    match = _BUILD_STAMP_RE.search(str(name or ""))
    return match.group(1) if match else None


def filter_assets_for_platform(
    names: list[str],
    *,
    platform: str | None = None,
) -> list[str]:
    """Keep release assets that match the running OS (avoid cross-OS stamp noise)."""
    plat = platform or sys.platform
    if plat == "darwin":
        return [name for name in names if name.lower().endswith(".dmg")]
    if plat == "win32":
        return [
            name
            for name in names
            if name.lower().endswith(".msi") or name.lower().endswith("portable.zip")
        ]
    return list(names)


def max_build_stamp(names: list[str]) -> str | None:
    best: str | None = None
    for name in names:
        stamp = parse_build_stamp(name)
        if not stamp:
            continue
        if best is None or stamp > best:
            best = stamp
    return best


def build_stamp_to_ms(stamp: str) -> int | None:
    match = re.fullmatch(
        r"(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})",
        stamp.strip(),
    )
    if not match:
        return None
    year = 2000 + int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    hour = int(match.group(4))
    minute = int(match.group(5))
    second = int(match.group(6))
    try:
        dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def resolve_update_kind(result: UpdateCheckResult) -> str | None:
    """Return 'version' | 'build' | None."""
    if not result.ok or not result.latest:
        return None
    cmp = _compare_versions(result.latest, result.current)
    if cmp > 0:
        return "version"
    if cmp < 0:
        return None

    # Same tag: only compare build stamps for this platform's packages.
    if not result.platform_assets_found:
        return None

    local = (result.current_build_stamp or "").strip()
    remote = (result.latest_build_stamp or "").strip()
    if local and remote and remote > local:
        return "build"

    # Same version, platform assets exist but lack stamps — use release time.
    if local and result.release_updated_at and not remote:
        local_at = build_stamp_to_ms(local)
        try:
            remote_at = int(
                datetime.fromisoformat(
                    result.release_updated_at.replace("Z", "+00:00")
                ).timestamp()
                * 1000
            )
        except ValueError:
            remote_at = None
        if local_at is not None and remote_at is not None and remote_at > local_at:
            return "build"
    return None


def update_notice_key(result: UpdateCheckResult) -> tuple[str, str, str]:
    """Identity of the release a startup notice would be about, for this OS."""
    return (
        sys.platform,
        (result.latest or "").strip(),
        (result.latest_build_stamp or "").strip(),
    )


def is_startup_notice_skipped(
    skipped: tuple[str, str, str],
    result: UpdateCheckResult,
) -> bool:
    """True when the user asked not to be told about this OS's current release."""
    platform, version, stamp = update_notice_key(result)
    if not version:
        return False
    return skipped == (platform, version, stamp)


def _current_label(result: UpdateCheckResult) -> str:
    base = version_label()
    stamp = (result.current_build_stamp or "").strip()
    if stamp and stamp != "000000_000000":
        return f"{base} ({stamp})"
    return base


_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/soonpyopark/Tiny-PDF-Editor/releases/latest"
)


def release_result_from_http(
    status: int,
    body: str,
    *,
    error: str | None = None,
    platform: str | None = None,
) -> UpdateCheckResult:
    current = __version__
    current_build_stamp = (APP_BUILD_STAMP or "").strip() or None
    if error:
        return UpdateCheckResult(
            ok=False,
            current=current,
            current_build_stamp=current_build_stamp,
            error=error,
        )
    if status >= 400:
        return UpdateCheckResult(
            ok=False,
            current=current,
            current_build_stamp=current_build_stamp,
            error=f"GitHub 응답 오류 (HTTP {status})",
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return UpdateCheckResult(
            ok=False,
            current=current,
            current_build_stamp=current_build_stamp,
            error="릴리스 정보를 해석할 수 없습니다.",
        )
    if not isinstance(payload, dict):
        return UpdateCheckResult(
            ok=False,
            current=current,
            current_build_stamp=current_build_stamp,
            error="릴리스 정보를 해석할 수 없습니다.",
        )

    tag_name = str(payload.get("tag_name") or "")
    latest = parse_release_tag(tag_name)
    if not latest:
        return UpdateCheckResult(
            ok=False,
            current=current,
            current_build_stamp=current_build_stamp,
            error=f"릴리스 버전을 해석할 수 없습니다: {tag_name or '(없음)'}",
        )

    assets = payload.get("assets") if isinstance(payload.get("assets"), list) else []
    asset_names = [
        str(item.get("name") or "") for item in assets if isinstance(item, dict)
    ]
    platform_names = filter_assets_for_platform(asset_names, platform=platform)
    latest_build_stamp = max_build_stamp(platform_names)
    release_updated_at = (
        str(payload.get("updated_at") or payload.get("published_at") or "").strip()
        or None
    )
    html_url = str(payload.get("html_url") or "").strip() or RELEASES_PAGE_URL
    return UpdateCheckResult(
        ok=True,
        current=current,
        current_build_stamp=current_build_stamp,
        latest=latest,
        latest_build_stamp=latest_build_stamp,
        release_updated_at=release_updated_at,
        release_url=html_url,
        platform_assets_found=bool(platform_names),
    )


def open_releases_page(url: str | None = None) -> None:
    QDesktopServices.openUrl(QUrl(url or RELEASES_PAGE_URL))


def _available_update_message(result: UpdateCheckResult) -> tuple[str, str]:
    current_hint = _current_label(result)
    latest = f"v{result.latest}"
    if result.update_kind == "build":
        stamp_hint = (
            f"\n최신 빌드: {result.latest_build_stamp}"
            if result.latest_build_stamp
            else ""
        )
        return (
            f"같은 버전의 새 빌드가 있습니다: {latest}",
            f"현재 버전: {current_hint}{stamp_hint}",
        )
    return (
        f"새 버전이 있습니다: {latest}",
        f"현재 버전: {current_hint}",
    )


def show_update_check_result(parent: QWidget | None, result: UpdateCheckResult) -> None:
    title = "업데이트 확인"
    current_hint = _current_label(result)
    if not result.ok:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText("업데이트 정보를 확인할 수 없습니다.")
        box.setInformativeText(
            f"{result.error or '알 수 없는 오류'}\n\n"
            f"현재 버전: {current_hint}"
        )
        open_btn = box.addButton("릴리스 페이지 열기", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            open_releases_page(RELEASES_PAGE_URL)
        return

    if result.update_kind is not None:
        text, detail = _available_update_message(result)
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText(detail)
        open_btn = box.addButton("다운로드", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            open_releases_page(result.release_url)
        return

    QMessageBox.information(
        parent,
        title,
        f"최신 버전입니다.\n\n현재 버전: {current_hint}",
    )


def show_startup_update_prompt(parent: QWidget | None, result: UpdateCheckResult) -> str:
    """Ask what to do with an available update. Returns download, later, or skip."""
    text, detail = _available_update_message(result)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("업데이트")
    box.setText(text)
    box.setInformativeText(detail)
    open_btn = box.addButton("다운로드", QMessageBox.ButtonRole.AcceptRole)
    later_btn = box.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
    skip_btn = box.addButton(
        "이 버전은 알리지 않기",
        QMessageBox.ButtonRole.ActionRole,
    )
    box.setDefaultButton(later_btn)
    box.setEscapeButton(later_btn)
    box.exec()
    clicked = box.clickedButton()
    if clicked is open_btn:
        return "download"
    if clicked is skip_btn:
        return "skip"
    return "later"


class UpdateCheckSession(QObject):
    """GitHub release check on the UI thread.

    HTTP/2 is disabled. Qt on a worker thread reported Connection closed
    against api.github.com.
    """

    def __init__(
        self,
        on_finished: Callable[[UpdateCheckResult], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_finished = on_finished
        self._running = True
        self._manager = QNetworkAccessManager(self)
        request = QNetworkRequest(QUrl(_LATEST_RELEASE_URL))
        request.setAttribute(
            QNetworkRequest.Attribute.Http2AllowedAttribute,
            False,
        )
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(
            b"User-Agent",
            f"{APP_NAME}/{__version__}".encode("ascii", "replace"),
        )
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setTransferTimeout(12_000)
        self._reply = self._manager.get(request)
        self._reply.finished.connect(self._finish)

    def isRunning(self) -> bool:
        return self._running

    def _finish(self) -> None:
        if not self._running:
            return
        self._running = False
        reply = self._reply
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        body = bytes(reply.readAll()).decode("utf-8", errors="replace")
        error = reply.error()
        reply.deleteLater()
        if error == QNetworkReply.NetworkError.TimeoutError:
            result = release_result_from_http(
                0,
                "",
                error="업데이트 확인 시간이 초과되었습니다.",
            )
        elif error != QNetworkReply.NetworkError.NoError and not status:
            result = release_result_from_http(
                0,
                "",
                error="업데이트 서버에 연결하지 못했습니다.",
            )
        else:
            result = release_result_from_http(int(status or 0), body)
        callback = self._on_finished
        self._on_finished = None
        if callback is not None:
            callback(result)
        self.deleteLater()


def start_update_check(
    parent: QObject | None,
    on_finished: Callable[[UpdateCheckResult], None],
) -> tuple[UpdateCheckSession, UpdateCheckSession]:
    """Start a release check. Caller must keep the returned refs until it finishes."""
    session = UpdateCheckSession(on_finished, parent)
    return session, session
