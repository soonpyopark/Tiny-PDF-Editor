"""Detect Korean PII and apply real PDF redaction (content removal).

Detection uses the MIT-licensed ``ko-pii`` library. Redaction uses PyMuPDF
``add_redact_annot`` / ``apply_redactions`` so underlying text is removed
(not merely covered by a black box). Algorithm inspired by public PDF
redaction practice; no third-party AGPL application code is vendored.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

import fitz

try:
    from ko_pii import detect_all
except ImportError:  # pragma: no cover - surfaced in UI
    detect_all = None  # type: ignore[assignment]


class RedactStyle(str, Enum):
    BLACK = "black"
    LABEL = "label"


LABEL_DISPLAY: dict[str, str] = {
    "PERSON": "성명",
    "RRN": "주민등록번호",
    "FRN": "외국인등록번호",
    "PHONE": "전화번호",
    "EMAIL": "이메일",
    "ADDRESS": "주소",
    "ACCOUNT": "계좌번호",
    "CARD": "카드번호",
    "PASSPORT": "여권번호",
    "DRIVER_LICENSE": "운전면허",
    "BUSINESS_REG": "사업자등록번호",
    "CORP_REG": "법인등록번호",
    "VEHICLE": "차량번호",
    "IP": "IP",
    "URL": "URL",
    "BIRTHDATE": "생년월일",
    "AGE": "나이",
    "POSITION": "직책",
}

# Prefer structural identifiers; PERSON/ADDRESS can be noisier.
DEFAULT_LABELS = frozenset(
    {
        "PERSON",
        "RRN",
        "FRN",
        "PHONE",
        "EMAIL",
        "ADDRESS",
        "ACCOUNT",
        "CARD",
        "PASSPORT",
        "DRIVER_LICENSE",
        "BUSINESS_REG",
        "CORP_REG",
        "VEHICLE",
        "BIRTHDATE",
    }
)

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class PiiHit:
    page_index: int
    label: str
    text: str
    rects: tuple[fitz.Rect, ...] = field(default_factory=tuple)

    @property
    def label_display(self) -> str:
        return LABEL_DISPLAY.get(self.label, self.label)

    @property
    def has_geometry(self) -> bool:
        return bool(self.rects)


@dataclass(frozen=True)
class PiiScanResult:
    hits: tuple[PiiHit, ...]
    pages_scanned: int
    pages_without_text: int
    text_chars: int

    @property
    def locatable_count(self) -> int:
        return sum(1 for hit in self.hits if hit.has_geometry)


def ko_pii_available() -> bool:
    return detect_all is not None


def label_display(label: str) -> str:
    return LABEL_DISPLAY.get(label, label)


def _search_variants(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    variants: list[str] = [raw]
    compact = _WS_RE.sub("", raw)
    if compact and compact not in variants:
        variants.append(compact)
    dashed = raw.replace("-", "")
    if dashed and dashed not in variants:
        variants.append(dashed)
    return variants


def _rects_for_text(page: fitz.Page, text: str) -> list[fitz.Rect]:
    found: list[fitz.Rect] = []
    seen: set[tuple[float, float, float, float]] = set()
    for variant in _search_variants(text):
        try:
            matches = page.search_for(variant)
        except Exception:
            matches = []
        for rect in matches:
            key = (
                round(rect.x0, 2),
                round(rect.y0, 2),
                round(rect.x1, 2),
                round(rect.y1, 2),
            )
            if key in seen:
                continue
            seen.add(key)
            found.append(fitz.Rect(rect))
    return found


def scan_document_bytes(
    pdf_bytes: bytes,
    *,
    include_labels: frozenset[str] | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> PiiScanResult:
    if detect_all is None:
        raise RuntimeError(
            "ko-pii 패키지가 설치되어 있지 않습니다.\n"
            "pip install ko-pii 후 다시 시도하세요."
        )
    if not pdf_bytes:
        raise ValueError("문서가 비어 있습니다.")

    labels = include_labels if include_labels is not None else DEFAULT_LABELS
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    hits: list[PiiHit] = []
    pages_without_text = 0
    text_chars = 0
    pages_scanned = 0
    try:
        pages_scanned = len(doc)
        for page_index, page in enumerate(doc):
            if status_callback is not None:
                status_callback(
                    f"개인정보 검사 중... {page_index + 1}/{pages_scanned}"
                )
            page_text = page.get_text("text") or ""
            text_chars += len(page_text)
            if not page_text.strip():
                pages_without_text += 1
                continue
            try:
                detections = detect_all(page_text)
            except Exception as exc:
                raise RuntimeError(f"{page_index + 1}페이지 검출 실패: {exc}") from exc
            for det in detections:
                label = str(getattr(det, "label", "") or "")
                text = str(getattr(det, "text", "") or "").strip()
                if not label or not text:
                    continue
                if labels and label not in labels:
                    continue
                rects = _rects_for_text(page, text)
                hits.append(
                    PiiHit(
                        page_index=page_index,
                        label=label,
                        text=text,
                        rects=tuple(rects),
                    )
                )
    finally:
        doc.close()

    return PiiScanResult(
        hits=tuple(hits),
        pages_scanned=pages_scanned,
        pages_without_text=pages_without_text,
        text_chars=text_chars,
    )


def _cjk_fontfile() -> str | None:
    candidates: list[str]
    if sys.platform == "darwin":
        candidates = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/Library/Fonts/AppleGothic.ttf",
            "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
    elif sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidates = [
            os.path.join(windir, "Fonts", "malgun.ttf"),
            os.path.join(windir, "Fonts", "gulim.ttc"),
            os.path.join(windir, "Fonts", "batang.ttc"),
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _ensure_label_font(page: fitz.Page, fontfile: str | None) -> str:
    if not fontfile:
        return "helv"
    fontname = "ko-pii-label"
    try:
        page.insert_font(fontname=fontname, fontfile=fontfile)
    except Exception:
        # Font may already be registered on this page.
        pass
    return fontname


def _draw_label(
    page: fitz.Page,
    rect: fitz.Rect,
    label: str,
    *,
    fontname: str,
) -> None:
    text = f"[{label_display(label)}]" if fontname != "helv" else f"[{label}]"
    fontsize = max(6.0, min(10.0, rect.height * 0.7))
    try:
        page.insert_textbox(
            rect,
            text,
            fontname=fontname,
            fontsize=fontsize,
            color=(1, 1, 1),
            align=fitz.TEXT_ALIGN_CENTER,
        )
    except Exception:
        pass


def redact_document_bytes(
    pdf_bytes: bytes,
    hits: list[PiiHit],
    *,
    style: RedactStyle = RedactStyle.BLACK,
    status_callback: Callable[[str], None] | None = None,
) -> tuple[bytes, int]:
    """Apply redactions for hits that have page geometry. Returns (pdf, count)."""
    if not pdf_bytes:
        raise ValueError("문서가 비어 있습니다.")
    selected = [hit for hit in hits if hit.has_geometry]
    if not selected:
        raise ValueError("제거할 위치가 확인된 개인정보가 없습니다.")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    applied = 0
    try:
        by_page: dict[int, list[PiiHit]] = {}
        for hit in selected:
            by_page.setdefault(hit.page_index, []).append(hit)

        total_pages = len(by_page)
        for step, (page_index, page_hits) in enumerate(sorted(by_page.items()), start=1):
            if status_callback is not None:
                status_callback(
                    f"개인정보 제거 중... {step}/{total_pages} "
                    f"(페이지 {page_index + 1})"
                )
            if not (0 <= page_index < len(doc)):
                continue
            page = doc[page_index]
            labeled_rects: list[tuple[fitz.Rect, str]] = []
            for hit in page_hits:
                for rect in hit.rects:
                    if rect.is_empty or rect.is_infinite:
                        continue
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                    applied += 1
                    if style == RedactStyle.LABEL:
                        labeled_rects.append((fitz.Rect(rect), hit.label))
            page.apply_redactions()
            if labeled_rects:
                fontname = _ensure_label_font(page, _cjk_fontfile())
                for rect, label in labeled_rects:
                    _draw_label(page, rect, label, fontname=fontname)

        if applied == 0:
            raise ValueError("적용할 수 있는 레닥션 영역이 없습니다.")
        payload = doc.tobytes(garbage=4, deflate=True, use_objstms=True)
        return payload, applied
    finally:
        doc.close()
