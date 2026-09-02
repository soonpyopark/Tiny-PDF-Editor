"""Check for newer releases on GitHub (version + platform build stamp)."""

from __future__ import annotations

import http.client
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from PyQt6.QtCore import QObject, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox, QWidget

from pdf_editor.version import APP_BUILD_STAMP, APP_NAME, __version__, version_label

GITHUB_REPO = "soonpyopark/Tiny-PDF-Editor"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"

_USER_AGENT = f"{APP_NAME}/{__version__}"
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


def _current_label(result: UpdateCheckResult) -> str:
    base = version_label()
    stamp = (result.current_build_stamp or "").strip()
    if stamp and stamp != "000000_000000":
        return f"{base} ({stamp})"
    return base


def fetch_latest_release(
    *,
    timeout_sec: float = 12.0,
    platform: str | None = None,
) -> UpdateCheckResult:
    current = __version__
    current_build_stamp = (APP_BUILD_STAMP or "").strip() or None
    try:
        conn = http.client.HTTPSConnection("api.github.com", timeout=timeout_sec)
        conn.request(
            "GET",
            "/repos/soonpyopark/Tiny-PDF-Editor/releases/latest",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": _USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = conn.getresponse()
        status = response.status
        body = response.read().decode("utf-8")
        conn.close()
    except Exception as exc:  # noqa: BLE001 — surface any network/parse failure
        return UpdateCheckResult(
            ok=False,
            current=current,
            current_build_stamp=current_build_stamp,
            error=str(exc) or "네트워크 오류",
        )
    if status >= 400:
        return UpdateCheckResult(
            ok=False,
            current=current,
            current_build_stamp=current_build_stamp,
            error=f"GitHub 응답 오류 (HTTP {status})",
        )
    payload = json.loads(body)

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


class UpdateCheckWorker(QObject):
    finished = pyqtSignal(object)

    def run(self) -> None:
        self.finished.emit(fetch_latest_release())


def open_releases_page(url: str | None = None) -> None:
    QDesktopServices.openUrl(QUrl(url or RELEASES_PAGE_URL))


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

    kind = result.update_kind
    if kind is not None:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        latest = f"v{result.latest}"
        if kind == "build":
            stamp_hint = (
                f"\n최신 빌드: {result.latest_build_stamp}"
                if result.latest_build_stamp
                else ""
            )
            box.setText(f"같은 버전의 새 빌드가 있습니다: {latest}")
            box.setInformativeText(f"현재 버전: {current_hint}{stamp_hint}")
        else:
            box.setText(f"새 버전이 있습니다: {latest}")
            box.setInformativeText(f"현재 버전: {current_hint}")
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


def start_update_check(
    parent: QObject | None,
    on_finished: Callable[[UpdateCheckResult], None],
) -> tuple[QThread, UpdateCheckWorker]:
    """Run release check off the UI thread. Caller must keep the returned refs."""
    thread = QThread(parent)
    worker = UpdateCheckWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    def _deliver(result: object) -> None:
        try:
            assert isinstance(result, UpdateCheckResult)
            on_finished(result)
        finally:
            thread.quit()

    worker.finished.connect(_deliver, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread, worker
