"""Convert plain text / Markdown files to temporary PDFs for insert/open.

Uses ``page.insert_text`` with reserved ``korea`` / ``helv`` font names (no TTF
embed), so Korean notes stay small. Markdown is rendered (headings, lists,
emphasis) rather than left as raw ``**markers**``.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json"}

_PAGE = fitz.paper_rect("a4")
_MARGIN = 48.0
_LINE_GAP = 1.35


@dataclass(frozen=True)
class _Run:
    text: str
    bold: bool = False
    code: bool = False


@dataclass(frozen=True)
class _Block:
    kind: str  # para | heading | bullet | number | code | hr
    runs: tuple[_Run, ...] = ()
    level: int = 1
    number: int = 1


def is_text_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in TEXT_EXTENSIONS


def read_text_file(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def convert_text_file_to_temp_pdf(path: str | Path) -> Path:
    """Write a temp PDF and return its path (caller deletes)."""
    pdf = convert_text_file_to_pdf_bytes(path)
    tmp = tempfile.NamedTemporaryFile(prefix="tiny-text-", suffix=".pdf", delete=False)
    tmp.write(pdf)
    tmp.close()
    return Path(tmp.name)


def convert_text_file_to_pdf(path: str | Path, output: str | Path) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(convert_text_file_to_pdf_bytes(path))
    return out


def convert_text_file_to_pdf_bytes(path: str | Path) -> bytes:
    text = read_text_file(path)
    ext = Path(path).suffix.lower()
    if ext in {".md", ".markdown"}:
        blocks = _parse_markdown(text)
    elif ext == ".json":
        try:
            import json

            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except Exception:
            pass
        blocks = _parse_plain(text)
    else:
        blocks = _parse_plain(text)
    return _blocks_to_pdf_bytes(blocks)


def _needs_cjk(text: str) -> bool:
    return any(ord(ch) > 0x2000 for ch in text)


def _fontname(text: str, *, bold: bool = False, code: bool = False) -> str:
    if code and not _needs_cjk(text):
        return "cour"
    if _needs_cjk(text):
        return "korea"
    if bold:
        return "hebo"
    return "helv"


def _parse_plain(text: str) -> list[_Block]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return [_Block(kind="para", runs=(_Run(""),))]
    blocks: list[_Block] = []
    for chunk in normalized.split("\n\n"):
        body = chunk.rstrip("\n")
        if body:
            # Keep single newlines inside a paragraph as line breaks via separate paras
            # when the user used blank-line-separated blocks; within a block keep \n.
            blocks.append(_Block(kind="para", runs=(_Run(body),)))
    return blocks or [_Block(kind="para", runs=(_Run(""),))]


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_HR = re.compile(r"^\s*((?:[-*_]\s*){3,})$")
_FENCE = re.compile(r"^```")


def _parse_inline(text: str) -> tuple[_Run, ...]:
    runs: list[_Run] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("`", i):
            end = text.find("`", i + 1)
            if end < 0:
                runs.append(_Run(text[i:]))
                break
            runs.append(_Run(text[i + 1 : end], code=True))
            i = end + 1
            continue
        if text.startswith("**", i) or text.startswith("__", i):
            mark = text[i : i + 2]
            end = text.find(mark, i + 2)
            if end < 0:
                runs.append(_Run(text[i:]))
                break
            runs.append(_Run(text[i + 2 : end], bold=True))
            i = end + 2
            continue
        if text.startswith("*", i) or text.startswith("_", i):
            mark = text[i]
            end = text.find(mark, i + 1)
            if end < 0:
                runs.append(_Run(text[i:]))
                break
            runs.append(_Run(text[i + 1 : end]))
            i = end + 1
            continue
        if text[i] == "[":
            close = text.find("]", i + 1)
            if close > i and close + 1 < n and text[close + 1] == "(":
                end = text.find(")", close + 2)
                if end > close:
                    runs.append(_Run(text[i + 1 : close]))
                    i = end + 1
                    continue
        next_special = n
        for token in ("`", "**", "__", "*", "_", "["):
            pos = text.find(token, i)
            if 0 <= pos < next_special:
                next_special = pos
        runs.append(_Run(text[i:next_special]))
        i = next_special
    return tuple(r for r in runs if r.text) or (_Run(""),)


def _parse_markdown(text: str) -> list[_Block]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    blocks: list[_Block] = []
    i = 0
    para_buf: list[str] = []

    def flush_para() -> None:
        nonlocal para_buf
        if not para_buf:
            return
        body = " ".join(part.strip() for part in para_buf if part.strip())
        para_buf = []
        if body:
            blocks.append(_Block(kind="para", runs=_parse_inline(body)))

    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line.strip()):
            flush_para()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not _FENCE.match(lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            blocks.append(_Block(kind="code", runs=(_Run("\n".join(code_lines)),)))
            continue
        if _HR.match(line):
            flush_para()
            blocks.append(_Block(kind="hr"))
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_para()
            blocks.append(
                _Block(
                    kind="heading",
                    level=len(heading.group(1)),
                    runs=_parse_inline(heading.group(2).strip()),
                )
            )
            i += 1
            continue
        ul = _UL.match(line)
        if ul:
            flush_para()
            blocks.append(_Block(kind="bullet", runs=_parse_inline(ul.group(2).strip())))
            i += 1
            continue
        ol = _OL.match(line)
        if ol:
            flush_para()
            blocks.append(
                _Block(
                    kind="number",
                    number=int(ol.group(2)),
                    runs=_parse_inline(ol.group(3).strip()),
                )
            )
            i += 1
            continue
        if not line.strip():
            flush_para()
            i += 1
            continue
        para_buf.append(line.strip())
        i += 1
    flush_para()
    return blocks or [_Block(kind="para", runs=(_Run(""),))]


def _fontsize_for(block: _Block) -> float:
    if block.kind == "heading":
        return {1: 18.0, 2: 15.0, 3: 13.0}.get(block.level, 12.0)
    if block.kind == "code":
        return 9.5
    return 11.0


def _measure(text: str, fontname: str, fontsize: float) -> float:
    try:
        return fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
    except Exception:
        return len(text) * fontsize * 0.5


def _wrap_line_segments(
    segments: list[tuple[str, str, float, bool]],
    max_width: float,
) -> list[list[tuple[str, str, float, bool]]]:
    """Wrap already-built (font, text, size, fake_bold) segments into visual lines."""
    lines: list[list[tuple[str, str, float, bool]]] = []
    current: list[tuple[str, str, float, bool]] = []
    width = 0.0

    def commit() -> None:
        nonlocal current, width
        if current:
            lines.append(current)
        current = []
        width = 0.0

    for fontname, text, size, fake_bold in segments:
        if text == "\n":
            commit()
            continue
        # Prefer wrapping on spaces; otherwise character-wise (CJK).
        tokens = re.findall(r"\S+\s*|\s+", text) if " " in text or "\t" in text else list(text)
        if not tokens:
            tokens = [text]
        for token in tokens:
            if not token:
                continue
            w = _measure(token, fontname, size)
            if current and width + w > max_width and token.strip():
                commit()
            if not current and not token.strip():
                continue
            # Hard-break overlong tokens.
            if w > max_width and len(token) > 1:
                for ch in token:
                    cw = _measure(ch, fontname, size)
                    if current and width + cw > max_width:
                        commit()
                    current.append((fontname, ch, size, fake_bold))
                    width += cw
                continue
            if current and width + w > max_width:
                commit()
            current.append((fontname, token, size, fake_bold))
            width += w
    commit()
    return lines or [[]]


def _block_segments(block: _Block, fontsize: float) -> list[tuple[str, str, float, bool]]:
    segments: list[tuple[str, str, float, bool]] = []
    if block.kind == "bullet":
        prefix = "• "
        segments.append((_fontname(prefix), prefix, fontsize, False))
    elif block.kind == "number":
        prefix = f"{block.number}. "
        segments.append((_fontname(prefix), prefix, fontsize, False))

    if block.kind == "code":
        text = block.runs[0].text if block.runs else ""
        fontname = _fontname(text, code=True)
        for index, line in enumerate(text.split("\n")):
            if index:
                segments.append((fontname, "\n", fontsize, False))
            segments.append((fontname, line if line else " ", fontsize, False))
        return segments

    for run in block.runs:
        fontname = _fontname(run.text, bold=run.bold, code=run.code)
        fake_bold = bool(run.bold and fontname == "korea")
        # Preserve explicit newlines inside a plain-text paragraph.
        parts = run.text.split("\n")
        for index, part in enumerate(parts):
            if index:
                segments.append((fontname, "\n", fontsize, False))
            if part:
                segments.append((fontname, part, fontsize, fake_bold))
    return segments


def _blocks_to_pdf_bytes(blocks: list[_Block]) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE.width, height=_PAGE.height)
    x0 = _MARGIN
    y = _MARGIN
    x1 = _PAGE.width - _MARGIN
    bottom = _PAGE.height - _MARGIN
    max_width = x1 - x0

    def ensure_space(need: float) -> None:
        nonlocal page, y
        if y + need <= bottom:
            return
        page = doc.new_page(width=_PAGE.width, height=_PAGE.height)
        y = _MARGIN

    for block in blocks:
        if block.kind == "hr":
            ensure_space(14)
            y += 4
            page.draw_line(
                fitz.Point(x0, y),
                fitz.Point(x1, y),
                width=0.6,
                color=(0.55, 0.55, 0.55),
            )
            y += 10
            continue

        size = _fontsize_for(block)
        segments = _block_segments(block, size)
        lines = _wrap_line_segments(segments, max_width)
        leading = size * _LINE_GAP
        if block.kind == "heading":
            y += size * 0.3
        for line_segs in lines:
            ensure_space(leading)
            x = x0
            for fontname, text, fsize, fake_bold in line_segs:
                if not text or text == "\n":
                    continue
                baseline = y + fsize * 0.82
                try:
                    page.insert_text(
                        fitz.Point(x, baseline),
                        text,
                        fontname=fontname,
                        fontsize=fsize,
                        overlay=True,
                    )
                except Exception:
                    page.insert_text(
                        fitz.Point(x, baseline),
                        text,
                        fontname="helv",
                        fontsize=fsize,
                        overlay=True,
                    )
                if fake_bold:
                    try:
                        page.insert_text(
                            fitz.Point(x + 0.35, baseline),
                            text,
                            fontname=fontname,
                            fontsize=fsize,
                            overlay=True,
                        )
                    except Exception:
                        pass
                x += _measure(text, fontname, fsize)
            y += leading
        y += 6 if block.kind == "heading" else 4

    pdf = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return pdf
