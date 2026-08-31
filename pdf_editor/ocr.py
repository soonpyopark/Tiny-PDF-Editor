"""Sidecar PaddleOCR helper: find pack, run worker, insert invisible text."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths

from pdf_editor.app_settings import AppSettings
from pdf_editor.document import PdfDocument

_settings: AppSettings | None = None


def bind_ocr_settings(settings: AppSettings) -> None:
    global _settings
    _settings = settings

OCR_HELPER_EXE = "ocr_helper.exe"
OCR_HELPER_BIN = "ocr_helper.exe" if os.name == "nt" else "ocr_helper"
OCR_HELPER_PY = "ocr_helper.py"
OCR_README_NAME = "여기에 OCR 구성 요소를 넣으세요.txt"
OCR_DPI = 300
SKIP_TEXT_CHARS = 20
HELPER_TIMEOUT_SEC = 180.0

GITHUB_RELEASES_URL = "https://github.com/soonpyopark/Tiny-PDF-Editor/releases"
PADDLEOCR_URL = "https://github.com/PaddlePaddle/PaddleOCR"

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class OcrHelper:
    ocr_dir: Path
    command: list[str]


@dataclass(frozen=True)
class OcrRunResult:
    applied_pages: int
    skipped_pages: int
    failed_pages: int
    word_count: int


class OcrHelperError(RuntimeError):
    """Helper missing, failed, or returned unusable output."""


def app_data_ocr_dir() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not base:
        base = str(Path.home() / ".tiny_pdf_editor")
    return Path(base) / "ocr"


def portable_ocr_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if sys.platform == "darwin":
            for parent in exe.parents:
                if parent.suffix == ".app":
                    sibling = parent.parent / "ocr"
                    if parent.parent.name == "Applications":
                        return app_data_ocr_dir()
                    return sibling
        return exe.parent / "ocr"
    return _REPO_ROOT / "ocr"


def assigned_ocr_dir() -> Path | None:
    if _settings is None:
        return None
    raw = (_settings.ocr_folder or "").strip()
    if not raw:
        return None
    return Path(raw)


def default_ocr_dir() -> Path:
    return portable_ocr_dir()


def active_ocr_dir() -> Path:
    assigned = assigned_ocr_dir()
    if assigned is not None:
        return assigned
    return default_ocr_dir()


def uses_custom_ocr_dir() -> bool:
    return assigned_ocr_dir() is not None


def set_custom_ocr_dir(folder: str | Path | None) -> Path:
    if _settings is None:
        raise RuntimeError("OCR 설정이 연결되지 않았습니다.")
    if folder is None or not str(folder).strip():
        _settings.ocr_folder = ""
        _settings.save()
        return default_ocr_dir()
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    _settings.ocr_folder = str(path.resolve())
    _settings.save()
    return path


def ocr_search_dirs() -> list[Path]:
    assigned = assigned_ocr_dir()
    if assigned is not None:
        return [assigned]
    dirs: list[Path] = []
    for candidate in (default_ocr_dir(), app_data_ocr_dir()):
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def preferred_ocr_dir() -> Path:
    return active_ocr_dir()


def _helper_in_dir(folder: Path) -> OcrHelper | None:
    for name in (OCR_HELPER_BIN, OCR_HELPER_EXE, "ocr_helper"):
        binary = folder / name
        if binary.is_file():
            if os.name != "nt":
                try:
                    binary.chmod(0o755)
                except OSError:
                    pass
            return OcrHelper(folder, [str(binary)])
    script = folder / OCR_HELPER_PY
    if script.is_file():
        python = sys.executable if not getattr(sys, "frozen", False) else "python"
        return OcrHelper(folder, [python, str(script)])
    return None


def find_ocr_helper() -> OcrHelper | None:
    for folder in ocr_search_dirs():
        found = _helper_in_dir(folder)
        if found is not None:
            return found
    if assigned_ocr_dir() is None and not getattr(sys, "frozen", False):
        bundled = _REPO_ROOT / "tools" / "ocr_helper"
        found = _helper_in_dir(bundled)
        if found is not None:
            return found
    return None


def ocr_helper_available() -> bool:
    return find_ocr_helper() is not None


def ocr_readme_text() -> str:
    return (
        "Tiny PDF Editor OCR 구성 요소\n"
        "==========================\n\n"
        "이 폴더에 아래 파일을 넣어 주세요.\n\n"
        f"  {OCR_HELPER_BIN}\n"
        "  _internal/       (도우미와 같이 압축에 들어 있음)\n"
        "  models/          (한글·한자·영어 인식 모델)\n"
        "  VERSION.txt      (선택)\n\n"
        "받는 곳:\n"
        f"  {GITHUB_RELEASES_URL}\n"
        "  앱과 같은 릴리스 목록에서 OCR 팩을 받아 이 폴더에 압축을 푸세요.\n\n"
        "인터넷이 되는 PC에서 받은 뒤, 필요하면 이 폴더로 복사하면 됩니다.\n"
        "앱을 다시 실행하거나 OCR 메뉴를 다시 열면 인식이 켜집니다.\n"
    )


def ensure_ocr_dir() -> Path:
    folder = preferred_ocr_dir()
    folder.mkdir(parents=True, exist_ok=True)
    readme = folder / OCR_README_NAME
    if not readme.is_file():
        try:
            readme.write_text(ocr_readme_text(), encoding="utf-8")
        except OSError:
            pass
    return folder


def _trace_text(span: dict) -> str:
    text = span.get("text")
    if text:
        return str(text)
    chars = span.get("chars")
    if not isinstance(chars, list):
        return ""
    parts: list[str] = []
    for char in chars:
        if isinstance(char, dict):
            parts.append(str(char.get("c") or char.get("text") or ""))
        else:
            parts.append(str(char))
    return "".join(parts)


def _page_text_stats(page) -> tuple[int, int]:
    """Return (visible_chars, invisible_ocr_chars)."""
    try:
        traces = page.get_texttrace()
    except Exception:
        text = (page.get_text("text") or "").strip()
        return len(text), 0
    visible = 0
    invisible = 0
    for span in traces:
        text = _trace_text(span).strip()
        if not text:
            continue
        if int(span.get("render_mode", 0) or 0) == 3:
            invisible += len(text)
        else:
            visible += len(text)
    return visible, invisible


_BOOK_MARKS = set("『』「」\"'“”‘’")


def _plausible_english(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 2:
        return False
    latin = [char for char in letters if char.isascii()]
    if len(latin) < 2 or len(latin) / len(letters) < 0.85:
        return False
    vowels = sum(1 for char in latin if char.lower() in "aeiou")
    return vowels >= 1 and vowels / len(latin) >= 0.15


def _plausible_url(text: str) -> bool:
    value = (text or "").strip()
    if "." not in value:
        return False
    latin = sum(1 for char in value if char.isascii() and char.isalpha())
    if latin < 4:
        return False
    tokens = value.replace("(", " ").replace(")", " ").split()
    return any(
        "." in token
        and sum(1 for char in token if char.isascii() and char.isalpha()) >= 4
        for token in tokens
    )


def _is_book_mark(text: str) -> bool:
    value = (text or "").strip()
    return bool(value) and all(char in _BOOK_MARKS for char in value)


def _is_short_latin(text: str) -> bool:
    value = (text or "").strip()
    return 1 <= len(value) <= 3 and all(
        char.isascii() and (char.isalpha() or char in ".-'") for char in value
    ) and any(char.isalpha() for char in value)


def _has_cjk(text: str) -> bool:
    return any(
        "\uac00" <= char <= "\ud7a3" or "\u4e00" <= char <= "\u9fff"
        for char in text
    )


def _keep_ocr_text(text: str, conf: float) -> str:
    """Keep Hangul, Hanja, Latin letters such as X, and book marks."""
    value = (text or "").strip()
    if not value or conf < 0.70:
        return ""
    hangul = sum(1 for char in value if "\uac00" <= char <= "\ud7a3")
    hanja = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    latin = sum(1 for char in value if char.isascii() and char.isalpha())
    compact = "".join(value.split())
    if ("/" in compact or "%" in compact) and not _plausible_url(value):
        digits = sum(1 for char in compact if char.isdigit())
        if digits >= 2 and hangul < 4 and hanja < 1 and latin < 2:
            return ""
    if hangul >= 2 or hanja >= 1:
        return value
    if _is_book_mark(value) or _is_short_latin(value) or _plausible_url(value):
        return value
    if _plausible_english(value) and conf >= 0.80:
        return value
    return ""


def _item_y_overlap(left: dict, right: dict) -> float:
    try:
        ay0, ay1 = float(left["y0"]), float(left["y1"])
        by0, by1 = float(right["y0"]), float(right["y1"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    inter = min(ay1, by1) - max(ay0, by0)
    if inter <= 0:
        return 0.0
    return inter / max(1.0, min(ay1 - ay0, by1 - by0))


def _insert_text_by_x(host: dict, extra_text: str, extra: dict) -> str:
    text = str(host.get("text") or "")
    if not text:
        return extra_text
    if extra_text and extra_text in text:
        return text
    if "..." in text and (_plausible_url(extra_text) or _plausible_english(extra_text)):
        return text.replace("...", extra_text, 1)
    try:
        x0, x1 = float(host["x0"]), float(host["x1"])
        extra_mid = 0.5 * (float(extra["x0"]) + float(extra["x1"]))
    except (KeyError, TypeError, ValueError):
        return text + extra_text
    width = max(1.0, x1 - x0)
    target = (extra_mid - x0) / width * len(text)
    index = max(0, min(len(text), int(round(target))))
    return text[:index] + extra_text + text[index:]


def _inject_script_tokens(base: list[dict], extras: list[dict]) -> list[dict]:
    """Put short Latin/Hanja (X, 東野圭吾) onto the overlapping Korean line."""
    items = [dict(item) for item in base]
    leftover: list[dict] = []
    for extra in extras:
        try:
            conf = float(extra.get("conf") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        text = _keep_ocr_text(str(extra.get("text") or ""), conf)
        if not text:
            continue
        hangul = sum(1 for char in text if "\uac00" <= char <= "\ud7a3")
        if hangul >= 2:
            continue
        host = None
        best = 0.0
        for item in items:
            overlap = _item_y_overlap(item, extra)
            if overlap < 0.35 or not _has_cjk(str(item.get("text") or "")):
                continue
            try:
                if float(extra["x1"]) < float(item["x0"]) - 4:
                    continue
                if float(extra["x0"]) > float(item["x1"]) + 4:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            if overlap > best:
                best = overlap
                host = item
        short = _is_short_latin(text) or _is_book_mark(text) or (
            sum(1 for char in text if "\u4e00" <= char <= "\u9fff") >= 1
            and hangul == 0
            and len(text) <= 12
        )
        injectable = short or _plausible_url(text) or _plausible_english(text)
        if host is not None and injectable:
            host["text"] = _insert_text_by_x(host, text, extra)
            continue
        if host is None:
            leftover.append({**extra, "text": text, "conf": conf})
    items.extend(leftover)
    return items


def page_has_text(document: PdfDocument, page_index: int) -> bool:
    page = document._doc[page_index]
    visible, _invisible = _page_text_stats(page)
    return visible >= SKIP_TEXT_CHARS


def _clear_invisible_ocr(page) -> None:
    visible, invisible = _page_text_stats(page)
    if invisible <= 0 or visible >= SKIP_TEXT_CHARS:
        return
    page.add_redact_annot(page.rect)
    try:
        page.apply_redactions(images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0))
    except TypeError:
        page.apply_redactions()


def _run_helper(
    helper: OcrHelper,
    image_path: Path,
    *,
    strip: bool = False,
    lang: str = "ko+en",
) -> list[dict]:
    out_path = image_path.with_name(
        f"{image_path.stem}_{lang}{'_strip' if strip else ''}.json"
    )
    command = [
        *helper.command,
        "--image",
        str(image_path),
        "--output",
        str(out_path),
        "--ocr-dir",
        str(helper.ocr_dir),
        "--lang",
        lang,
    ]
    if strip:
        command.append("--strip")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=HELPER_TIMEOUT_SEC,
            check=False,
            creationflags=creationflags,
            cwd=str(helper.ocr_dir),
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrHelperError(
            "OCR 처리 시간이 초과되었습니다.\n페이지가 너무 크거나 도우미가 응답하지 않습니다."
        ) from exc
    except OSError as exc:
        raise OcrHelperError(f"OCR 도우미를 실행할 수 없습니다.\n{exc}") from exc

    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise OcrHelperError(f"OCR 도우미가 실패했습니다.\n{detail}")
    if not out_path.is_file():
        raise OcrHelperError("OCR 도우미가 결과 파일을 만들지 않았습니다.")
    try:
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OcrHelperError("OCR 결과 JSON을 읽을 수 없습니다.") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise OcrHelperError("OCR 결과 형식이 올바르지 않습니다.")
    return [item for item in items if isinstance(item, dict)]


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _cluster_ocr_rows(items: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in sorted(items, key=lambda row: (float(row.get("y0") or 0), float(row.get("x0") or 0))):
        try:
            y0 = float(item["y0"])
            y1 = float(item["y1"])
        except (KeyError, TypeError, ValueError):
            continue
        center = 0.5 * (y0 + y1)
        placed = False
        for row in rows:
            if row["y0"] <= center <= row["y1"]:
                row["items"].append(item)
                row["y0"] = min(row["y0"], y0)
                row["y1"] = max(row["y1"], y1)
                placed = True
                break
        if not placed:
            rows.append({"y0": y0, "y1": y1, "items": [item]})
    return rows


def _row_column(row: dict) -> tuple[float, float]:
    xs0 = [float(item["x0"]) for item in row["items"]]
    xs1 = [float(item["x1"]) for item in row["items"]]
    return min(xs0), max(xs1)


def _crop_page_image(image_path: Path, y0: int, y1: int) -> Path | None:
    try:
        source = fitz.Pixmap(str(image_path))
        clip = fitz.IRect(0, y0, source.width, y1)
        if clip.is_empty or clip.height < 8:
            return None
        cropped = fitz.Pixmap(source.colorspace, clip, source.alpha)
        cropped.copy(source, clip)
        crop_path = image_path.with_name(f"{image_path.stem}_gap{y0}.png")
        cropped.save(str(crop_path))
        return crop_path
    except Exception:
        return None


def _refill_ocr_gaps(helper: OcrHelper, image_path: Path, items: list[dict]) -> list[dict]:
    """Re-read skipped body lines so selection does not jump over them."""
    rows = _cluster_ocr_rows(items)
    if len(rows) < 3:
        return items
    heights = [row["y1"] - row["y0"] for row in rows]
    gaps = [b["y0"] - a["y1"] for a, b in zip(rows, rows[1:]) if b["y0"] > a["y1"]]
    med_h = _median(heights)
    med_g = _median(gaps) if gaps else med_h * 0.35
    if med_h <= 0:
        return items
    threshold = max(med_h * 0.85, med_g * 1.8)
    filled = list(items)
    try:
        page_h = fitz.Pixmap(str(image_path)).height
    except Exception:
        return items
    for previous, nxt in zip(rows, rows[1:]):
        gap = nxt["y0"] - previous["y1"]
        title_gap = previous is rows[0] and (previous["y1"] - previous["y0"]) < med_h * 1.4
        if gap < threshold and not (title_gap and gap > med_h * 0.8):
            continue
        if gap > med_h * 6 and not title_gap:
            continue
        y0 = max(0, int(previous["y1"] - med_h * 0.1))
        y1 = min(page_h, int(nxt["y0"] + med_h * 0.1))
        if y1 - y0 < 8 or y0 > page_h * 0.92:
            continue
        crop_path = _crop_page_image(image_path, y0, y1)
        if crop_path is None:
            continue
        try:
            extra = _run_helper(helper, crop_path, strip=True)
        except OcrHelperError:
            extra = []
        finally:
            crop_path.unlink(missing_ok=True)
            crop_path.with_suffix(".json").unlink(missing_ok=True)
        col_x0, col_x1 = _row_column(previous)
        next_x0, next_x1 = _row_column(nxt)
        col_x0 = min(col_x0, next_x0)
        col_x1 = max(col_x1, next_x1)
        kept: list[dict] = []
        for item in extra:
            try:
                conf = float(item.get("conf") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            text = _keep_ocr_text(str(item.get("text") or ""), conf)
            if not text:
                continue
            try:
                kept.append(
                    {
                        "text": text,
                        "conf": conf,
                        "x0": float(item["x0"]),
                        "y0": float(item["y0"]) + y0,
                        "x1": float(item["x1"]),
                        "y1": float(item["y1"]) + y0,
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        for row in _cluster_ocr_rows(kept):
            parts = sorted(row["items"], key=lambda item: float(item["x0"]))
            text = "".join(str(item.get("text") or "") for item in parts)
            hangul = sum(1 for char in text if "\uac00" <= char <= "\ud7a3")
            hanja = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
            latin = sum(1 for char in text if char.isascii() and char.isalpha())
            if hangul < 8 and hanja < 1 and latin < 1:
                continue
            confs = [float(item.get("conf") or 0.0) for item in parts]
            filled.append(
                {
                    "text": text,
                    "conf": sum(confs) / len(confs) if confs else 0.0,
                    "x0": col_x0,
                    "y0": min(float(item["y0"]) for item in parts),
                    "x1": col_x1,
                    "y1": max(float(item["y1"]) for item in parts),
                }
            )
    return filled


def _horizontal_ink_bands(gray, min_height: int = 10) -> list[tuple[int, int]]:
    width, height = gray.size
    pixels = gray.load()
    thresh = max(8, int(width * 0.015))
    bands: list[tuple[int, int]] = []
    row = 0
    while row < height:
        ink = sum(1 for x in range(width) if pixels[x, row] < 175)
        if ink < thresh:
            row += 1
            continue
        top = row
        while row < height:
            ink = sum(1 for x in range(width) if pixels[x, row] < 175)
            if ink < thresh:
                break
            row += 1
        if row - top >= min_height:
            bands.append((top, row))
    return bands


def _ink_x_span(gray, pad: int = 6) -> tuple[int, int] | None:
    ink = _column_ink(gray)
    min_ink = max(2, int(gray.size[1] * 0.08))
    xs = [index for index, value in enumerate(ink) if value >= min_ink]
    if not xs:
        return None
    return max(0, xs[0] - pad), min(gray.size[0], xs[-1] + pad)


def _y_covered_by_items(y0: float, y1: float, items: list[dict]) -> bool:
    height = max(1.0, y1 - y0)
    for item in items:
        try:
            iy0, iy1 = float(item["y0"]), float(item["y1"])
        except (KeyError, TypeError, ValueError):
            continue
        inter = min(y1, iy1) - max(y0, iy0)
        if inter / height >= 0.35:
            return True
    return False


def _ocr_tight_crop(
    helper: OcrHelper,
    image_path: Path,
    box: tuple[int, int, int, int],
    *,
    lang: str,
) -> list[dict]:
    gray, origin = _gray_crop(image_path, *box)
    if gray is None:
        return []
    span = _ink_x_span(gray)
    if span is None:
        return []
    ox, oy, _, _ = origin
    left, right = span
    crop_box = (ox + left, oy, ox + right, box[3])
    crop, crop_origin = _gray_crop(
        image_path,
        int(crop_box[0]),
        int(crop_box[1]),
        int(crop_box[2] + 0.999),
        int(crop_box[3] + 0.999),
    )
    if crop is None:
        return []
    try:
        from PIL import Image
    except ImportError:
        return []
    long_side = max(crop.size)
    if long_side < 160:
        scale = min(3.0, 240 / max(1, long_side))
        crop = crop.resize(
            (max(8, int(crop.size[0] * scale)), max(8, int(crop.size[1] * scale))),
            Image.Resampling.LANCZOS,
        )
    crop_path = image_path.with_name(
        f"{image_path.stem}_rec_{lang}_{crop_box[0]}_{crop_box[1]}.png"
    )
    try:
        crop.convert("RGB").save(str(crop_path))
        extra = _run_helper(helper, crop_path, strip=True, lang=lang)
    except (OcrHelperError, OSError):
        extra = []
    finally:
        crop_path.unlink(missing_ok=True)
        crop_path.with_name(f"{crop_path.stem}_{lang}_strip.json").unlink(missing_ok=True)
        crop_path.with_suffix(".json").unlink(missing_ok=True)
    cx, cy, _, _ = crop_origin
    scale_x = (crop_box[2] - crop_box[0]) / max(1, crop.size[0]) if crop.size[0] else 1.0
    scale_y = (crop_box[3] - crop_box[1]) / max(1, crop.size[1]) if crop.size[1] else 1.0
    placed: list[dict] = []
    for item in extra:
        try:
            conf = float(item.get("conf") or 0.0)
            text = _keep_ocr_text(str(item.get("text") or ""), conf)
            if not text:
                continue
            placed.append(
                {
                    "text": text,
                    "conf": conf,
                    "x0": cx + float(item["x0"]) * scale_x,
                    "y0": cy + float(item["y0"]) * scale_y,
                    "x1": cx + float(item["x1"]) * scale_x,
                    "y1": cy + float(item["y1"]) * scale_y,
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return placed


def _recover_missed_scripts(
    helper: OcrHelper, image_path: Path, items: list[dict]
) -> list[dict]:
    """Read Hanja lines and lone Latin letters (X) that the Korean pass skipped."""
    try:
        from PIL import Image
    except ImportError:
        return items
    try:
        page = Image.open(image_path).convert("L")
    except Exception:
        return items
    recovered = list(items)
    for top, bottom in _horizontal_ink_bands(page):
        if bottom - top > 90 or top > page.height * 0.90:
            continue
        if _y_covered_by_items(top, bottom, recovered):
            continue
        found = _ocr_tight_crop(
            helper, image_path, (0, top, page.width, bottom), lang="korean"
        )
        if not found:
            found = _ocr_tight_crop(
                helper, image_path, (0, top, page.width, bottom), lang="ch"
            )
        for item in found:
            text = str(item.get("text") or "")
            if not text:
                continue
            recovered.append(item)
    for item in list(recovered):
        text = str(item.get("text") or "")
        latin = sum(1 for char in text if char.isascii() and char.isalpha())
        needs_latin = (
            "홈페이지" in text
            or "ISBN" in text.upper()
            or "..." in text
            or ("학습" in text and "AI" not in text.upper())
            or "www" in text.lower()
            or "http" in text.lower()
        )
        try:
            x0, y0, x1, y1 = (
                int(item["x0"]),
                int(item["y0"]),
                int(item["x1"] + 0.999),
                int(item["y1"] + 0.999),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if needs_latin and latin < 6:
            extras = _ocr_tight_crop(
                helper, image_path, (x0, y0, x1, y1), lang="en"
            )
            if extras:
                recovered = _inject_script_tokens(recovered, extras)
                continue
        if not _has_cjk(text):
            continue
        gray, origin = _gray_crop(image_path, x0, y0, x1, y1)
        if gray is None:
            continue
        ox, oy, _, _ = origin
        em = max(8.0, gray.size[1] * 0.58)
        for left, right in _ink_segments(_column_ink(gray), gray.size[1]):
            width = right - left
            if width < em * 0.28 or width > em * 1.45:
                continue
            extras = _ocr_tight_crop(
                helper,
                image_path,
                (ox + left, oy, ox + right, y1),
                lang="en",
            )
            if extras:
                recovered = _inject_script_tokens(recovered, extras)
    return recovered


def _gray_crop(image_path: Path, x0: int, y0: int, x1: int, y1: int):
    try:
        from PIL import Image
    except ImportError:
        return None, (x0, y0, x1, y1)
    try:
        picture = Image.open(image_path).convert("L")
    except Exception:
        return None, (x0, y0, x1, y1)
    left = max(0, x0)
    top = max(0, y0)
    right = min(picture.width, x1)
    bottom = min(picture.height, y1)
    if right - left < 8 or bottom - top < 4:
        return None, (left, top, right, bottom)
    return picture.crop((left, top, right, bottom)), (left, top, right, bottom)


def _column_ink(gray) -> list[int]:
    width, height = gray.size
    pixels = gray.load()
    ink = [0] * width
    for x in range(width):
        ink[x] = sum(1 for y in range(height) if pixels[x, y] < 175)
    return ink


def _ink_runs(ink: list[int], min_ink: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(ink):
        if ink[index] < min_ink:
            index += 1
            continue
        start = index
        while index < len(ink) and ink[index] >= min_ink:
            index += 1
        if index - start >= 2:
            runs.append((start, index))
    return runs


def _ink_segments(ink: list[int], height: int) -> list[tuple[int, int]]:
    if not ink or height <= 0:
        return []
    min_ink = max(2, int(height * 0.08))
    runs = _ink_runs(ink, min_ink)
    if len(runs) <= 1:
        return runs
    gaps = [runs[index][0] - runs[index - 1][1] for index in range(1, len(runs))]
    letter = [gap for gap in gaps if gap <= max(8, int(height * 0.18))]
    typical = sorted(letter)[len(letter) // 2] if letter else 4
    split_gap = max(12, int(typical * 2.8), int(height * 0.26))
    merged: list[tuple[int, int]] = [runs[0]]
    for run, gap in zip(runs[1:], gaps):
        if gap < split_gap:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return _merge_narrow_word_blobs(merged, height)


def _merge_narrow_word_blobs(
    segments: list[tuple[int, int]], height: int
) -> list[tuple[int, int]]:
    """Join one-glyph blobs created by justified spacing."""
    if len(segments) <= 1:
        return segments
    em = max(8.0, height * 0.58)
    limit = em * 1.35
    weak_gap = max(16, int(height * 0.38))
    merged: list[tuple[int, int]] = [segments[0]]
    for segment in segments[1:]:
        prev = merged[-1]
        gap = segment[0] - prev[1]
        prev_w = prev[1] - prev[0]
        cur_w = segment[1] - segment[0]
        if prev_w < limit and cur_w < limit and 0 <= gap < weak_gap:
            merged[-1] = (prev[0], segment[1])
        else:
            merged.append(segment)
    while len(merged) >= 2:
        prev = merged[-2]
        last = merged[-1]
        gap = last[0] - prev[1]
        if last[1] - last[0] < limit and 0 <= gap < weak_gap:
            merged[-2] = (prev[0], last[1])
            merged.pop()
            continue
        break
    return merged


def _char_unit(char: str) -> float:
    if char.isdigit() or (char.isascii() and char.isalpha()):
        return 0.55
    if char in ".,·'\"“”‘’『』[]()-%/":
        return 0.55
    if char in " ":
        return 0.35
    return 1.0


_TRAILING_PUNCT = set(".,，、;:)]》»』\"'“”’")


def _ocr_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for char in "".join(text.split()):
        if not tokens:
            tokens.append(char)
            continue
        prev = tokens[-1]
        if char in _TRAILING_PUNCT or (
            char.isdigit() and prev[-1].isdigit()
        ) or (
            char in "년회" and prev[-1].isdigit()
        ):
            tokens[-1] += char
        else:
            tokens.append(char)
    return tokens


def _token_unit(token: str) -> float:
    return sum(_char_unit(char) for char in token)


def _split_text_by_widths(text: str, widths: list[float], line_height: float) -> list[str]:
    tokens = _ocr_tokens(text)
    if not tokens or not widths:
        return [text] if text else []
    if len(widths) == 1:
        return ["".join(tokens)]
    n_tok = len(tokens)
    n_seg = len(widths)
    if n_seg > n_tok:
        return ["".join(tokens)]
    em = max(8.0, line_height * 0.58)
    units = [_token_unit(token) for token in tokens]
    prefix = [0.0]
    for unit in units:
        prefix.append(prefix[-1] + unit)

    def segment_cost(start: int, end: int, width: float) -> float:
        if end <= start:
            return 1e18
        expected = (prefix[end] - prefix[start]) * em
        return (expected - width) ** 2

    infinite = 1e18
    cost = [[infinite] * (n_tok + 1) for _ in range(n_seg + 1)]
    back: list[list[int]] = [[-1] * (n_tok + 1) for _ in range(n_seg + 1)]
    cost[0][0] = 0.0
    for seg in range(1, n_seg + 1):
        low = seg
        high = n_tok - (n_seg - seg)
        for used in range(low, high + 1):
            best = infinite
            best_at = -1
            for prev in range(seg - 1, used):
                previous = cost[seg - 1][prev]
                if previous >= infinite:
                    continue
                trial = previous + segment_cost(prev, used, widths[seg - 1])
                if trial < best:
                    best = trial
                    best_at = prev
            cost[seg][used] = best
            back[seg][used] = best_at
    if cost[n_seg][n_tok] >= infinite:
        return ["".join(tokens)]
    parts: list[str] = []
    seg = n_seg
    used = n_tok
    while seg > 0:
        prev = back[seg][used]
        parts.append("".join(tokens[prev:used]))
        used = prev
        seg -= 1
    parts.reverse()
    return parts


def _refine_gap_items(items: list[dict]) -> list[dict]:
    """Move leading punctuation and year/counter syllables onto the previous word."""
    leading = ".,，、;:)]》»』\"'“”’"
    refined: list[dict] = []
    for item in items:
        text = str(item.get("text") or "")
        x0 = float(item["x0"])
        x1 = float(item["x1"])
        width = max(1.0, x1 - x0)
        while refined and text and text[0] in leading:
            refined[-1]["text"] = str(refined[-1]["text"]) + text[0]
            refined[-1]["x1"] = max(float(refined[-1]["x1"]), x0 + width / max(1, len(text)))
            text = text[1:]
            x0 = float(refined[-1]["x1"])
        if refined and text:
            prev = str(refined[-1]["text"])
            steal = ""
            if text.startswith("년") and prev[-1:].isdigit():
                steal = "년"
            elif text.startswith("회") and prev[-1:].isdigit():
                steal = "회"
            elif (
                text.startswith("상")
                and len(text) > 1
                and text[1].isdigit()
                and prev
            ):
                steal = "상"
            elif prev.endswith("제") and text[:1].isdigit():
                refined[-1]["text"] = prev[:-1]
                text = "제" + text
                if not refined[-1]["text"]:
                    refined.pop()
            if steal:
                share = width / max(1, len(text))
                refined[-1]["text"] = prev + steal
                refined[-1]["x1"] = max(float(refined[-1]["x1"]), x0 + share)
                text = text[len(steal):]
                x0 = float(refined[-1]["x1"])
        if not text:
            if refined:
                refined[-1]["x1"] = max(float(refined[-1]["x1"]), x1)
            continue
        refined.append({**item, "text": text, "x0": x0, "x1": x1})
    return refined if refined else items


def _split_item_by_image_gaps(image_path: Path, item: dict) -> list[dict]:
    """Split one OCR line into visual words using ink gaps on the page image."""
    text = str(item.get("text") or "").strip()
    try:
        x0 = float(item["x0"])
        y0 = float(item["y0"])
        x1 = float(item["x1"])
        y1 = float(item["y1"])
        conf = float(item.get("conf") or 0.0)
    except (KeyError, TypeError, ValueError):
        return [item]
    if not text or x1 - x0 < 12:
        return [item]
    gray, origin = _gray_crop(
        image_path, int(x0), int(y0), int(x1 + 0.999), int(y1 + 0.999)
    )
    if gray is None:
        return [item]
    ox, oy, _, _ = origin
    segments = _ink_segments(_column_ink(gray), gray.size[1])
    if not segments:
        return [item]
    if len(segments) == 1:
        left, right = segments[0]
        return [
            {
                **item,
                "text": text,
                "x0": ox + left,
                "x1": ox + right,
            }
        ]
    tokens = _ocr_tokens(text)
    if len(segments) > len(tokens):
        return [item]
    widths = [float(right - left) for left, right in segments]
    parts = _split_text_by_widths(text, widths, float(gray.size[1]))
    if len(parts) != len(segments):
        return [item]
    split: list[dict] = []
    for part, (left, right) in zip(parts, segments):
        value = (part or "").strip()
        if not value:
            continue
        split.append(
            {
                "text": value,
                "conf": conf,
                "x0": ox + left,
                "y0": y0,
                "x1": ox + right,
                "y1": y1,
            }
        )
    if not split:
        return [item]
    return _refine_gap_items(split)


def _split_ocr_items_to_image_gaps(
    image_path: Path, items: list[dict]
) -> list[dict]:
    spaced: list[dict] = []
    for item in items:
        parts = _split_item_by_image_gaps(image_path, item)
        texts = [
            str(part.get("text") or "").strip()
            for part in parts
        ]
        texts = [text for text in texts if text]
        if not texts:
            continue
        spaced.append({**item, "text": " ".join(texts)})
    return spaced


def _item_page_rect(item: dict, zoom: float, page_rect: fitz.Rect) -> fitz.Rect | None:
    try:
        x0 = float(item["x0"]) / zoom
        y0 = float(item["y0"]) / zoom
        x1 = float(item["x1"]) / zoom
        y1 = float(item["y1"]) / zoom
    except (KeyError, TypeError, ValueError):
        return None
    rect = fitz.Rect(x0, y0, x1, y1)
    rect.normalize()
    if rect.is_empty or rect.is_infinite:
        return None
    clipped = rect & page_rect
    if clipped.is_empty:
        return None
    return clipped


def run_ocr_on_document(
    document: PdfDocument,
    page_indices: list[int],
    *,
    status_callback: Callable[[str], None] | None = None,
    skip_existing_text: bool = True,
) -> OcrRunResult:
    helper = find_ocr_helper()
    if helper is None:
        raise OcrHelperError(
            "OCR 구성 요소가 없습니다.\n"
            "OCR 메뉴의 'OCR 팩 설치...'를 참고해 "
            f"{OCR_HELPER_BIN}를 OCR 폴더에 넣어 주세요."
        )
    indices = sorted(
        {
            index
            for index in page_indices
            if 0 <= index < document.page_count
        }
    )
    if not indices:
        return OcrRunResult(0, 0, 0, 0)

    zoom = OCR_DPI / 72.0
    applied = 0
    skipped = 0
    failed = 0
    words = 0
    recorded = False
    total = len(indices)
    work = Path(tempfile.mkdtemp(prefix="tiny_ocr_"))
    try:
        for step, page_index in enumerate(indices, start=1):
            if status_callback is not None:
                status_callback(f"OCR 중... {page_index + 1}페이지 ({step}/{total})")
            if skip_existing_text and page_has_text(document, page_index):
                skipped += 1
                continue
            image_path = work / f"page_{page_index + 1}.png"
            try:
                pix = document.render_page_pixmap(
                    page_index, zoom, annots=False, ignore_pause=True
                )
                pix.save(str(image_path))
                items = _refill_ocr_gaps(
                    helper, image_path, _run_helper(helper, image_path)
                )
                items = _recover_missed_scripts(helper, image_path, items)
                items.sort(
                    key=lambda item: (
                        float(item.get("y0") or 0),
                        float(item.get("x0") or 0),
                    )
                )
                filtered: list[dict] = []
                for item in items:
                    raw = str(item.get("text") or "").strip()
                    try:
                        conf = float(item.get("conf") or 0.0)
                    except (TypeError, ValueError):
                        conf = 0.0
                    text = _keep_ocr_text(raw, conf)
                    if not text:
                        continue
                    filtered.append({**item, "text": text, "conf": conf})
                items = _split_ocr_items_to_image_gaps(image_path, filtered)
                page_rect = document.get_page_rect(page_index)
                spans: list[tuple[str, fitz.Rect]] = []
                for item in items:
                    text = str(item.get("text") or "").strip()
                    if not text:
                        continue
                    rect = _item_page_rect(item, zoom, page_rect)
                    if rect is None:
                        continue
                    spans.append((text, rect))
                if not spans:
                    skipped += 1
                    continue
                if not recorded:
                    document._record_undo_checkpoint()
                    recorded = True
                _clear_invisible_ocr(document._doc[page_index])
                count = document.apply_ocr_spans(page_index, spans)
                if count:
                    applied += 1
                    words += count
                else:
                    skipped += 1
            except OcrHelperError:
                raise
            except Exception as exc:
                failed += 1
                if status_callback is not None:
                    status_callback(f"{page_index + 1}페이지 실패: {exc}")
    finally:
        for leftover in work.glob("*"):
            try:
                leftover.unlink()
            except OSError:
                pass
        try:
            work.rmdir()
        except OSError:
            pass
    return OcrRunResult(applied, skipped, failed, words)
