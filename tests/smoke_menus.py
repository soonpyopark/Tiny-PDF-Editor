"""Headless-ish menu smoke: invoke menu handlers without blocking file dialogs.

Run:
  .\\.venv\\Scripts\\python.exe tests\\smoke_menus.py
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

import pymupdf as fitz
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdf_editor.main_window import MainWindow
from pdf_editor.signature_stamp import (
    copy_signature_png_to_clipboard,
    prepare_signature_from_qimage,
)


class SmokeReport:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.skipped: list[tuple[str, str]] = []

    def ok(self, name: str) -> None:
        self.passed.append(name)
        print(f"  OK   {name}")

    def fail(self, name: str, err: BaseException | str) -> None:
        msg = str(err)
        self.failed.append((name, msg))
        print(f"  FAIL {name}: {msg}")

    def skip(self, name: str, reason: str) -> None:
        self.skipped.append((name, reason))
        print(f"  SKIP {name}: {reason}")


def _silence_message_boxes() -> None:
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[method-assign]
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[method-assign]
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[method-assign]
    QMessageBox.question = staticmethod(  # type: ignore[method-assign]
        lambda *a, **k: QMessageBox.StandardButton.Yes
    )


def _close_dialogs_soon(app: QApplication, delay_ms: int = 200) -> None:
    def _close() -> None:
        for widget in list(app.topLevelWidgets()):
            if isinstance(widget, QDialog) and widget.isVisible():
                widget.reject()

    QTimer.singleShot(delay_ms, _close)


def _make_pdf(path: Path, *, rotation: int = 0, pages: int = 2) -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Smoke page {i + 1}", fontsize=16)
        if rotation:
            page.set_rotation(rotation)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    return path


def _make_signature_png() -> bytes:
    image = QImage(160, 60, QImage.Format.Format_RGBA8888)
    image.fill(QColor(255, 255, 255, 0))
    painter = QPainter(image)
    painter.setPen(QColor(0, 0, 0))
    painter.drawText(20, 40, "SmokeSig")
    painter.fillRect(10, 10, 8, 40, QColor(0, 0, 0))
    painter.end()
    prepared = prepare_signature_from_qimage(image)
    assert prepared is not None
    return prepared.png_bytes


def _run(name: str, report: SmokeReport, fn) -> None:
    try:
        fn()
        QApplication.processEvents()
        report.ok(name)
    except Exception as exc:  # noqa: BLE001 — smoke must catch all
        traceback.print_exc()
        report.fail(name, exc)


def main() -> int:
    # Unbuffered progress for CI / background shells.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass
    app = QApplication.instance() or QApplication(sys.argv)
    _silence_message_boxes()
    report = SmokeReport()
    tmp = Path(tempfile.mkdtemp(prefix="tiny_smoke_"))
    plain_pdf = _make_pdf(tmp / "plain.pdf", rotation=0, pages=3)
    rotated_pdf = _make_pdf(tmp / "rot90.pdf", rotation=90, pages=2)
    sig_png = _make_signature_png()
    copy_signature_png_to_clipboard(sig_png)

    print("기동 중…", flush=True)
    win = MainWindow()
    # Avoid blocking network update check during smoke.
    win._update_check_thread = None
    if hasattr(win, "_check_for_updates_on_startup"):
        win._check_for_updates_on_startup = lambda: None  # type: ignore[method-assign]
    win.resize(1100, 800)
    win.show()
    app.processEvents()
    print("기동 완료", flush=True)

    def tab():
        return win._current_tab()

    print("== 파일 ==")
    _run("새 문서", report, win._new_tab)
    _run(
        "열기(plain)",
        report,
        lambda: win._open_paths([str(plain_pdf)], force_same_window=True),
    )
    _run(
        "추가",
        report,
        lambda: tab() and tab()._on_insert(tab().document.page_count, [str(rotated_pdf)]),
    )
    _run(
        "저장(임시)",
        report,
        lambda: tab() and tab().document.save(str(tmp / "saved.pdf")),
    )
    _run(
        "다른 이름 저장",
        report,
        lambda: tab() and tab().document.save(str(tmp / "saved_as.pdf")),
    )

    print("== 편집 ==")
    _run("되돌리기 가능여부 갱신", report, win._update_edit_actions)
    if tab() and tab().document.can_undo():
        _run("되돌리기", report, win._undo_current_tab)
        _run("재실행", report, win._redo_current_tab)
    else:
        report.skip("되돌리기/재실행", "undo stack empty after open path")

    _run("텍스트 검색 포커스", report, win._focus_search)
    _run(
        "모든 페이지 시계방향 회전",
        report,
        win._rotate_all_pages_cw,
    )
    _run(
        "모든 페이지 반시계방향 회전",
        report,
        win._rotate_all_pages_ccw,
    )

    print("== 서명 ==")
    _run(
        "서명 클립보드 시작",
        report,
        lambda: tab() and tab().begin_paste_signature(),
    )

    def commit_sig() -> None:
        t = tab()
        assert t is not None
        if not t.viewer.is_signature_stamp_active():
            ok, msg = t.begin_paste_signature()
            if not ok:
                raise RuntimeError(msg)
            app.processEvents()
        if not t.viewer.commit_signature_stamp():
            raise RuntimeError("commit_signature_stamp returned False")

    _run("서명 Enter 확정", report, commit_sig)

    def move_sig() -> None:
        t = tab()
        assert t is not None
        page_index = t.viewer.current_index()
        page = t.document.get_page_rect(page_index)
        point = fitz.Point(page.x1 - 40, page.y1 - 40)
        hit = t.document.find_signature_stamp_at(page_index, point)
        if hit is None:
            # try center of default bottom-right band
            hit = t.document.find_signature_stamp_at(
                page_index, fitz.Point(page.x1 * 0.85, page.y1 * 0.9)
            )
        if hit is None:
            raise RuntimeError("no signature hit after commit")
        new_rect = fitz.Rect(
            max(20, hit.rect.x0 - 100),
            max(20, hit.rect.y0 - 60),
            max(20, hit.rect.x0 - 100) + hit.rect.width,
            max(20, hit.rect.y0 - 60) + hit.rect.height,
        )
        t.document.replace_signature_stamp(hit, new_rect, sig_png, record_undo=True)
        t.viewer._refresh_pages_after_stamp()
        if t.document._signature_draw_present(t.document._doc[hit.page_index], hit.rect):
            # old may still register if overlap; check new present
            pass
        if not t.document._signature_draw_present(t.document._doc[page_index], new_rect):
            raise RuntimeError("moved stamp not present at new rect")

    _run("서명 이동(replace)", report, move_sig)

    def delete_sig() -> None:
        t = tab()
        assert t is not None
        page_index = t.viewer.current_index()
        page = t.document.get_page_rect(page_index)
        # scan for any signature annot
        hit = None
        for y in range(int(page.y0) + 10, int(page.y1), 40):
            for x in range(int(page.x0) + 10, int(page.x1), 40):
                hit = t.document.find_signature_stamp_at(page_index, fitz.Point(x, y))
                if hit is not None:
                    break
            if hit is not None:
                break
        if hit is None:
            raise RuntimeError("no signature to delete")
        t.document.delete_signature_stamp(hit, record_undo=True)
        t.viewer._refresh_pages_after_stamp()

    _run("서명 삭제", report, delete_sig)

    # Rotated PDF tab
    _run(
        "회전 PDF 열기",
        report,
        lambda: win._open_paths([str(rotated_pdf)], force_same_window=True),
    )

    def stamp_on_rotated() -> None:
        t = tab()
        assert t is not None
        ok, msg = t.begin_paste_signature()
        if not ok:
            raise RuntimeError(msg)
        app.processEvents()
        if not t.viewer.commit_signature_stamp():
            raise RuntimeError("commit on rotated failed")
        page = t.document._doc[0]
        # find any stamp image
        if not any(
            "fzImg" in str(item[7]) for item in (page.get_images(full=True) or [])
        ):
            # still ok if present via draw
            pass
        rects = []
        for item in page.get_images(full=True) or []:
            try:
                rects.append(page.get_image_bbox(item))
            except Exception:
                continue
        if not rects:
            raise RuntimeError("no image bbox after stamp on rotated page")

    _run("회전 PDF 서명 확정", report, stamp_on_rotated)

    print("== 보기 ==")
    _run(
        "너비 맞추기",
        report,
        lambda: tab() and tab().viewer.fit_width(),
    )
    _run(
        "높이 맞추기",
        report,
        lambda: tab() and tab().viewer.fit_height(),
    )
    _run(
        "화면 맞추기",
        report,
        lambda: tab() and tab().viewer.fit_page(),
    )
    _run("두 쪽씩 보기 토글", report, lambda: win._toggle_facing_pages(True))
    _run("두 쪽씩 보기 원복", report, lambda: win._toggle_facing_pages(False))
    _run("전체 화면 ON", report, win._toggle_fullscreen)
    _run("전체 화면 OFF", report, win._toggle_fullscreen)

    print("== 다이얼로그 오픈/즉시 닫기 ==")

    def _open_and_close(opener, wait_ms: int = 400) -> None:
        closed = {"done": False}

        def _close() -> None:
            for widget in list(app.topLevelWidgets()):
                if widget is win:
                    continue
                try:
                    if isinstance(widget, QDialog) and widget.isVisible():
                        widget.reject()
                    elif widget.isVisible() and widget is not win:
                        widget.close()
                except Exception:
                    pass
            closed["done"] = True

        QTimer.singleShot(wait_ms, _close)
        opener()
        # Pump events until close timer fires (cap 3s).
        for _ in range(60):
            app.processEvents()
            if closed["done"]:
                break
            app.processEvents()
            QTimer.singleShot(0, lambda: None)
            app.processEvents()
            import time

            time.sleep(0.05)

    for name, opener in [
        ("용량 줄이기 대화상자", win._open_reduce_size_dialog),
        ("쪽 번호 대화상자", win._open_page_number_dialog),
        ("개인정보 제거 대화상자", lambda: win._open_pii_remove_dialog()),
    ]:
        _run(name, report, lambda op=opener: _open_and_close(op))

    _run("인쇄 대화상자", report, lambda: _open_and_close(win._print, wait_ms=500))
    report.skip("정보(About)", "스플래시 오버레이 — 수동 확인 권장")

    # Password set with empty cancel path — open dialog if any
    report.skip("비밀번호 설정/제거", "모달 입력 UI — 수동 확인 권장")
    report.skip("OCR 실행", "모델·시간 소요 — 메뉴 활성만 확인")
    _run("OCR 메뉴 활성 갱신", report, win._update_ocr_actions)
    report.skip("PDF 병합 대화상자", "파일 선택 모달 — 수동 확인 권장")
    report.skip("HWP 변환", "한컴 의존 — 수동 확인 권장")
    report.skip("가상 프린터/파일 연결", "시스템 설정 UI — 수동 확인 권장")
    report.skip("업데이트 확인", "네트워크 — 수동 확인 권장")

    # Selection delete
    def _delete_page() -> None:
        t = tab()
        assert t is not None
        if t.document.page_count < 1:
            raise RuntimeError("no pages")
        # delete last page via document API used by menu
        indices = [t.document.page_count - 1]
        t._apply_page_deletion(indices)

    _run("선택 페이지 삭제", report, _delete_page)

    # Copy/cut/paste pages via thumbnails selection
    def _copy_paste_page() -> None:
        t = tab()
        assert t is not None
        t.thumbnails.set_current_index(0)
        win._copy_current_tab()
        app.processEvents()
        win._paste_current_tab()
        app.processEvents()

    _run("페이지 복사 후 붙여넣기", report, _copy_paste_page)

    # Avoid "저장할까요?" / save-file dialogs on close.
    for index in range(win.tabs.count()):
        widget = win.tabs.widget(index)
        doc = getattr(widget, "document", None)
        if doc is not None:
            doc._modified = False
    win.close()
    app.processEvents()

    print()
    print("==== 요약 ====")
    print(f"통과 {len(report.passed)} / 실패 {len(report.failed)} / 스킵 {len(report.skipped)}")
    if report.failed:
        print("실패 항목:")
        for name, msg in report.failed:
            print(f"  - {name}: {msg}")
        return 1
    print("메뉴 스모크: 치명 오류 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
