"""Check for newer releases on GitHub."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QObject, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox, QWidget

from pdf_editor.version import APP_NAME, __version__, version_label

GITHUB_REPO = "soonpyopark/Tiny-PDF-Editor"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"
RELEASES_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

_USER_AGENT = f"{APP_NAME}/{__version__}"
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    current: str
    latest: str | None = None
    release_url: str | None = None
    error: str | None = None

    @property
    def update_available(self) -> bool:
        if not self.ok or not self.latest:
            return False
        return _version_tuple(self.latest) > _version_tuple(self.current)


def _version_tuple(text: str) -> tuple[int, ...]:
    match = _VERSION_RE.search(text.strip())
    if not match:
        return (0,)
    return tuple(int(part) for part in match.groups())


def parse_release_tag(tag_name: str) -> str | None:
    match = _VERSION_RE.search(tag_name or "")
    if not match:
        return None
    return ".".join(match.groups())


def fetch_latest_release(
    *,
    timeout_sec: float = 12.0,
) -> UpdateCheckResult:
    current = __version__
    request = urllib.request.Request(
        RELEASES_LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return UpdateCheckResult(
            ok=False,
            current=current,
            error=f"GitHub 응답 오류 (HTTP {exc.code})",
        )
    except Exception as exc:  # noqa: BLE001 — surface any network/parse failure
        return UpdateCheckResult(
            ok=False,
            current=current,
            error=str(exc) or "네트워크 오류",
        )

    tag_name = str(payload.get("tag_name") or "")
    latest = parse_release_tag(tag_name)
    if not latest:
        return UpdateCheckResult(
            ok=False,
            current=current,
            error=f"릴리스 버전을 해석할 수 없습니다: {tag_name or '(없음)'}",
        )

    html_url = str(payload.get("html_url") or "").strip() or RELEASES_PAGE_URL
    return UpdateCheckResult(
        ok=True,
        current=current,
        latest=latest,
        release_url=html_url,
    )


class UpdateCheckWorker(QObject):
    finished = pyqtSignal(object)

    def run(self) -> None:
        self.finished.emit(fetch_latest_release())


def open_releases_page(url: str | None = None) -> None:
    QDesktopServices.openUrl(QUrl(url or RELEASES_PAGE_URL))


def show_update_check_result(parent: QWidget | None, result: UpdateCheckResult) -> None:
    title = "업데이트 확인"
    if not result.ok:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText("업데이트 정보를 확인할 수 없습니다.")
        box.setInformativeText(
            f"{result.error or '알 수 없는 오류'}\n\n"
            f"현재 버전: {version_label()}"
        )
        open_btn = box.addButton("릴리스 페이지 열기", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            open_releases_page(RELEASES_PAGE_URL)
        return

    if result.update_available:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(f"새 버전이 있습니다: v{result.latest}")
        box.setInformativeText(f"현재 버전: {version_label()}")
        open_btn = box.addButton("다운로드", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            open_releases_page(result.release_url)
        return

    QMessageBox.information(
        parent,
        title,
        f"최신 버전입니다.\n\n현재 버전: {version_label()}",
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
