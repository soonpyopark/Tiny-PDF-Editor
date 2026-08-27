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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum

import fitz

try:
    from ko_pii import detect_all
except ImportError:  # pragma: no cover - surfaced in UI
    detect_all = None  # type: ignore[assignment]


class RedactStyle(str, Enum):
    GRAY = "gray"
    BLACK = "black"
    LIGHT_BLUE = "light_blue"
    LIGHT_RED = "light_red"
    LABEL = "label"


DEFAULT_REDACT_STYLE = RedactStyle.GRAY

REDACT_FILL_RGB: dict[RedactStyle, tuple[float, float, float]] = {
    RedactStyle.GRAY: (0.72, 0.72, 0.72),
    RedactStyle.BLACK: (0.0, 0.0, 0.0),
    RedactStyle.LIGHT_BLUE: (0.70, 0.84, 0.95),
    RedactStyle.LIGHT_RED: (0.96, 0.76, 0.76),
    RedactStyle.LABEL: (0.0, 0.0, 0.0),
}

REDACT_STYLE_CHOICES: tuple[tuple[RedactStyle, str], ...] = (
    (RedactStyle.GRAY, "회색 박스"),
    (RedactStyle.BLACK, "검정 박스"),
    (RedactStyle.LIGHT_BLUE, "연한 파랑 박스"),
    (RedactStyle.LIGHT_RED, "연한 빨강 박스"),
    (RedactStyle.LABEL, "한글 라벨"),
)


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
_SEP_RE = re.compile(r"[\s\-–—·.•‧/\\:：]+")


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

    @property
    def area_count(self) -> int:
        return sum(len(hit.rects) for hit in self.hits if hit.has_geometry)


class ScanCancelled(Exception):
    """Raised when a PII scan is aborted from the UI."""


def ko_pii_available() -> bool:
    return detect_all is not None


def label_display(label: str) -> str:
    return LABEL_DISPLAY.get(label, label)


def hit_area_count(hits: list[PiiHit]) -> int:
    return sum(len(hit.rects) for hit in hits if hit.has_geometry)


def format_pii_count(hit_count: int, area_count: int) -> str:
    return f"{hit_count}건(영역 {area_count}개)"


def normalize_page_indices(
    page_indices: Sequence[int] | None,
    *,
    page_count: int | None = None,
) -> frozenset[int] | None:
    """Return a page set to scan, or None for the whole document."""
    if page_indices is None:
        return None
    unique = {int(index) for index in page_indices if int(index) >= 0}
    if page_count is not None:
        unique = {index for index in unique if index < page_count}
        if unique and len(unique) >= page_count:
            return None
    return frozenset(unique)


def format_pii_scope(
    page_indices: Sequence[int] | None,
    *,
    page_count: int | None = None,
) -> str:
    scoped = normalize_page_indices(page_indices, page_count=page_count)
    if scoped is None:
        return "전체 페이지"
    if not scoped:
        return "선택한 페이지"
    if len(scoped) == 1:
        return f"{next(iter(scoped)) + 1}페이지"
    return f"선택한 {len(scoped)}개 페이지"


def tighten_redact_rect(rect: fitz.Rect) -> fitz.Rect:
    """Inset slightly so redaction is less likely to swallow neighboring glyphs."""
    tight = fitz.Rect(rect)
    if tight.is_empty or tight.is_infinite:
        return tight
    inset_x = min(0.55, max(0.12, tight.width * 0.035))
    inset_y = min(0.45, max(0.08, tight.height * 0.10))
    tight.x0 += inset_x
    tight.x1 -= inset_x
    tight.y0 += inset_y
    tight.y1 -= inset_y
    if tight.is_empty or tight.width < 0.8 or tight.height < 0.8:
        return fitz.Rect(rect)
    return tight


def tightened_hit_rects(hit: PiiHit) -> list[fitz.Rect]:
    return [
        tighten_redact_rect(rect)
        for rect in hit.rects
        if not rect.is_empty and not rect.is_infinite
    ]


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


def _normalize_key(text: str) -> str:
    return _SEP_RE.sub("", text or "")


def _rect_key(rect: fitz.Rect) -> tuple[float, float, float, float]:
    return (
        round(rect.x0, 2),
        round(rect.y0, 2),
        round(rect.x1, 2),
        round(rect.y1, 2),
    )


def _merge_line_rects(rects: list[fitz.Rect]) -> list[fitz.Rect]:
    if not rects:
        return []
    ordered = sorted(rects, key=lambda rect: (round(rect.y0, 1), rect.x0))
    merged: list[fitz.Rect] = [fitz.Rect(ordered[0])]
    for rect in ordered[1:]:
        last = merged[-1]
        same_line = abs(rect.y0 - last.y0) <= max(3.0, last.height * 0.6)
        close = rect.x0 <= last.x1 + max(4.0, last.height)
        if same_line and close:
            merged[-1] = last | rect
        else:
            merged.append(fitz.Rect(rect))
    return merged


def _dedupe_rects(rects: list[fitz.Rect]) -> list[fitz.Rect]:
    seen: set[tuple[float, float, float, float]] = set()
    unique: list[fitz.Rect] = []
    for rect in rects:
        if rect.is_empty or rect.is_infinite:
            continue
        key = _rect_key(rect)
        if key in seen:
            continue
        seen.add(key)
        unique.append(fitz.Rect(rect))
    return unique


def _search_flags() -> int:
    flags = 0
    for name in ("TEXT_DEHYPHENATE", "TEXT_PRESERVE_WHITESPACE"):
        flags |= int(getattr(fitz, name, 0) or 0)
    return flags


def _rects_from_search(page: fitz.Page, text: str) -> list[fitz.Rect]:
    found: list[fitz.Rect] = []
    flags = _search_flags()
    for variant in _search_variants(text):
        try:
            matches = page.search_for(variant, flags=flags) if flags else page.search_for(variant)
        except TypeError:
            try:
                matches = page.search_for(variant)
            except Exception:
                matches = []
        except Exception:
            matches = []
        found.extend(fitz.Rect(rect) for rect in matches)
    return _dedupe_rects(found)


def _occurrence_index(page_text: str, needle: str, start: int | None) -> int:
    key = _normalize_key(needle)
    if not key:
        return 0
    hay = _normalize_key(page_text)
    compact_at = len(_normalize_key(page_text[: max(0, start)])) if start is not None else 0
    count = 0
    pos = 0
    while True:
        idx = hay.find(key, pos)
        if idx < 0:
            return max(0, count - 1) if count else 0
        if idx >= compact_at:
            return count
        count += 1
        pos = idx + 1


def _rects_from_stream(
    items: list[tuple[str, fitz.Rect]],
    needle: str,
) -> list[list[fitz.Rect]]:
    key = _normalize_key(needle)
    if not key or not items:
        return []
    stream: list[tuple[str, fitz.Rect]] = []
    for char, rect in items:
        for piece in _normalize_key(char):
            stream.append((piece, rect))
    hay = "".join(char for char, _ in stream)
    matches: list[list[fitz.Rect]] = []
    pos = 0
    while True:
        idx = hay.find(key, pos)
        if idx < 0:
            break
        matches.append(_merge_line_rects([stream[i][1] for i in range(idx, idx + len(key))]))
        pos = idx + 1
    return matches


def _word_char_stream(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    items: list[tuple[str, fitz.Rect]] = []
    try:
        words = page.get_text("words") or []
    except Exception:
        return items
    for word in words:
        text = str(word[4]) if len(word) > 4 else ""
        if not text:
            continue
        items.append((text, fitz.Rect(word[0], word[1], word[2], word[3])))
    return items


def _raw_char_stream(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    items: list[tuple[str, fitz.Rect]] = []
    try:
        data = page.get_text("rawdict") or {}
    except Exception:
        return items
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = span.get("chars") or []
                if chars:
                    for char in chars:
                        glyph = str(char.get("c") or "")
                        bbox = char.get("bbox")
                        if not glyph or not bbox:
                            continue
                        items.append((glyph, fitz.Rect(bbox)))
                    continue
                text = str(span.get("text") or "")
                bbox = span.get("bbox")
                if not text or not bbox:
                    continue
                items.append((text, fitz.Rect(bbox)))
    return items


def _pick_stream_rects(
    matches: list[list[fitz.Rect]],
    page_text: str,
    needle: str,
    start: int | None,
) -> list[fitz.Rect]:
    if not matches:
        return []
    index = _occurrence_index(page_text, needle, start)
    if 0 <= index < len(matches):
        return matches[index]
    return matches[0]


def _rects_for_hit(
    page: fitz.Page,
    text: str,
    *,
    page_text: str = "",
    start: int | None = None,
) -> list[fitz.Rect]:
    found = _rects_from_search(page, text)
    if found and (start is None or len(found) == 1):
        return found
    if found and start is not None:
        index = _occurrence_index(page_text, text, start)
        if 0 <= index < len(found):
            return [found[index]]
        return found[:1]
    for stream in (_word_char_stream(page), _raw_char_stream(page)):
        picked = _pick_stream_rects(
            _rects_from_stream(stream, text),
            page_text,
            text,
            start,
        )
        if picked:
            return picked
    return []


def scan_document_bytes(
    pdf_bytes: bytes,
    *,
    include_labels: frozenset[str] | None = None,
    page_indices: Sequence[int] | None = None,
    status_callback: Callable[[str], None] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
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
        target_indices = normalize_page_indices(page_indices, page_count=len(doc))
        scan_order = (
            range(len(doc))
            if target_indices is None
            else sorted(target_indices)
        )
        pages_scanned = len(scan_order)
        for step, page_index in enumerate(scan_order, start=1):
            page = doc[page_index]
            if cancel_callback is not None and cancel_callback():
                raise ScanCancelled()
            if progress_callback is not None:
                progress_callback(step, pages_scanned)
            if status_callback is not None:
                status_callback(
                    f"개인정보 검사 중... {page_index + 1}페이지 ({step}/{pages_scanned})"
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
                start = getattr(det, "start", None)
                try:
                    start_index = int(start) if start is not None else None
                except (TypeError, ValueError):
                    start_index = None
                rects = _rects_for_hit(
                    page,
                    text,
                    page_text=page_text,
                    start=start_index,
                )
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
    style: RedactStyle = DEFAULT_REDACT_STYLE,
    status_callback: Callable[[str], None] | None = None,
) -> tuple[bytes, int, int]:
    """Apply redactions. Returns (pdf, hit_count, area_count)."""
    if not pdf_bytes:
        raise ValueError("문서가 비어 있습니다.")
    selected = [hit for hit in hits if hit.has_geometry]
    if not selected:
        raise ValueError("제거할 위치가 확인된 개인정보가 없습니다.")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    applied_hits = 0
    applied_areas = 0
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
                hit_applied = False
                for rect in tightened_hit_rects(hit):
                    fill = REDACT_FILL_RGB.get(style, REDACT_FILL_RGB[DEFAULT_REDACT_STYLE])
                    page.add_redact_annot(rect, fill=fill)
                    applied_areas += 1
                    hit_applied = True
                    if style == RedactStyle.LABEL:
                        labeled_rects.append((fitz.Rect(rect), hit.label))
                if hit_applied:
                    applied_hits += 1
            page.apply_redactions()
            if labeled_rects:
                fontname = _ensure_label_font(page, _cjk_fontfile())
                for rect, label in labeled_rects:
                    _draw_label(page, rect, label, fontname=fontname)

        if applied_areas == 0:
            raise ValueError("적용할 수 있는 레닥션 영역이 없습니다.")
        payload = doc.tobytes(garbage=4, deflate=True, use_objstms=True)
        return payload, applied_hits, applied_areas
    finally:
        doc.close()
