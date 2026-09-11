#!/usr/bin/env python3
"""Paint Tiny PDF Editor brand icons from the 4-up guide and write .ico/.icns."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "pdf_editor" / "branding"
MASTER_DIR = ROOT / "assets" / "masters"
SOURCE_APP = ROOT / "assets" / "brand-app-icon.png"
SOURCE_FILE = ROOT / "assets" / "brand-file-icon.png"

MASTER_SIZE = 1024
_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
_ICNS_PIXELS = (16, 32, 64, 128, 256, 512, 1024)

WIN_TOP = (243, 109, 123)
WIN_BOT = (196, 48, 58)
WIN_FILE = (214, 70, 78)
WIN_FILE_FOLD = (252, 186, 190)
WIN_FILE_EDGE = (160, 32, 40)


def _font(size: int, *, heavy: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names: list[str]
    if sys.platform == "darwin":
        names = (
            [
                "/System/Library/Fonts/Supplemental/Arial Black.ttf",
                "/Library/Fonts/Arial Black.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            ]
            if heavy
            else [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ]
        )
    else:
        windir = Path(r"C:\Windows\Fonts")
        names = (
            [str(windir / "ariblk.ttf"), str(windir / "arialbd.ttf")]
            if heavy
            else [str(windir / "arialbd.ttf"), str(windir / "arial.ttf")]
        )
    for name in names:
        path = Path(name)
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    y = np.linspace(0.0, 1.0, size, dtype=np.float32)[:, None]
    color = np.array(top, dtype=np.float32) + (np.array(bottom, dtype=np.float32) - top) * y
    pixels = np.repeat(color.astype(np.uint8)[:, None, :], size, axis=1)
    return Image.fromarray(pixels, "RGB")


def _squircle_mask(size: int, radius: float) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    inset = 1
    draw.rounded_rectangle(
        (inset, inset, size - 1 - inset, size - 1 - inset),
        radius=int(size * radius),
        fill=255,
    )
    return mask


def _paste_masked(base: Image.Image, overlay: Image.Image, mask: Image.Image) -> Image.Image:
    out = base.convert("RGBA")
    plate = overlay.convert("RGBA")
    plate.putalpha(mask)
    out.alpha_composite(plate)
    return out


def _document_geometry(
    box: tuple[int, int, int, int],
    fold: int | None = None,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], int]:
    x0, y0, x1, y1 = box
    width = x1 - x0
    fold = fold if fold is not None else max(12, width // 5)
    body = [
        (x0, y0),
        (x1 - fold, y0),
        (x1, y0 + fold),
        (x1, y1),
        (x0, y1),
    ]
    corner = [(x1 - fold, y0), (x1, y0 + fold), (x1 - fold, y0 + fold)]
    return body, corner, fold


def _draw_document(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int],
    fold_fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
    fold: int | None = None,
) -> None:
    body, corner, _fold = _document_geometry(box, fold)
    draw.polygon(body, fill=fill, outline=outline)
    draw.polygon(corner, fill=fold_fill, outline=outline)


def _center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    cy: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    canvas: int,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = (canvas - width) // 2 - bbox[0]
    y = cy - height // 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill)


def _draw_brand_mark(
    draw: ImageDraw.ImageDraw,
    canvas: int,
    *,
    compact: bool,
    doc_fill: tuple[int, int, int],
    doc_fold: tuple[int, int, int],
    mark_fill: tuple[int, int, int],
    text_fill: tuple[int, int, int],
    subtitle: str,
    outline: tuple[int, int, int] | None = None,
    stacked: bool = True,
) -> None:
    if compact:
        doc_w, doc_h = int(canvas * 0.42), int(canvas * 0.50)
        cx, cy = canvas // 2, int(canvas * 0.48)
        x0 = cx - doc_w // 2
        y0 = cy - doc_h // 2
        if stacked:
            _draw_document(
                draw,
                (x0 - canvas // 28, y0 - canvas // 28, x0 - canvas // 28 + doc_w, y0 - canvas // 28 + doc_h),
                fill=doc_fill,
                fold_fill=doc_fold,
                outline=outline,
            )
        _draw_document(
            draw,
            (x0, y0, x0 + doc_w, y0 + doc_h),
            fill=doc_fill,
            fold_fill=doc_fold,
            outline=outline,
        )
        t_font = _font(max(10, int(canvas * 0.28)), heavy=True)
        _center_text(draw, "T", cy + canvas // 80, t_font, mark_fill, canvas)
        return

    doc_w, doc_h = int(canvas * 0.30), int(canvas * 0.34)
    cx = canvas // 2
    y0 = int(canvas * 0.18)
    x0 = cx - doc_w // 2
    shift = int(canvas * 0.035)
    if stacked:
        _draw_document(
            draw,
            (x0 - shift, y0 - shift, x0 - shift + doc_w, y0 - shift + doc_h),
            fill=doc_fill,
            fold_fill=doc_fold,
            outline=outline,
        )
    _draw_document(
        draw,
        (x0, y0, x0 + doc_w, y0 + doc_h),
        fill=doc_fill,
        fold_fill=doc_fold,
        outline=outline,
    )
    if not compact:
        badge = max(18, int(canvas * 0.12))
        bx = canvas // 2 - badge // 2
        by = y0 + int(doc_h * 0.22)
        draw.rounded_rectangle(
            (bx, by, bx + badge, by + badge),
            radius=max(3, badge // 6),
            fill=doc_fill,
            outline=mark_fill,
            width=max(1, canvas // 220),
        )
    t_font = _font(int(canvas * (0.14 if not compact else 0.16)), heavy=True)
    _center_text(draw, "T", y0 + int(doc_h * 0.48), t_font, mark_fill, canvas)
    tiny_font = _font(int(canvas * 0.09), heavy=True)
    sub_font = _font(int(canvas * 0.038), heavy=False)
    _center_text(draw, "TINY", int(canvas * 0.68), tiny_font, text_fill, canvas)
    _center_text(draw, subtitle, int(canvas * 0.78), sub_font, text_fill, canvas)


def _is_guide_backdrop(red: int, green: int, blue: int) -> bool:
    brightness = (red + green + blue) / 3
    spread = max(red, green, blue) - min(red, green, blue)
    return brightness >= 218 and spread <= 14


def _knockout_guide_backdrop(image: Image.Image) -> Image.Image:
    from collections import deque

    data = np.array(image.convert("RGBA"))
    height, width = data.shape[:2]
    visited = np.zeros((height, width), dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))
    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= width or y >= height or visited[y, x]:
            continue
        red, green, blue, _alpha = data[y, x]
        if not _is_guide_backdrop(int(red), int(green), int(blue)):
            continue
        visited[y, x] = True
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    data[visited, 3] = 0
    rows, cols = np.where(data[:, :, 3] > 0)
    if len(rows) == 0:
        return Image.fromarray(data)
    pad = 2
    top = max(0, int(rows.min()) - pad)
    bottom = min(height - 1, int(rows.max()) + pad)
    left = max(0, int(cols.min()) - pad)
    right = min(width - 1, int(cols.max()) + pad)
    return Image.fromarray(data[top : bottom + 1, left : right + 1])


def _fit_artwork(icon: Image.Image, size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fitted = icon.convert("RGBA")
    width, height = fitted.size
    if width <= 0 or height <= 0:
        return canvas
    scale = min(size / width, size / height)
    new_size = (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )
    if new_size != fitted.size:
        fitted = fitted.resize(new_size, Image.Resampling.LANCZOS)
    x = (size - fitted.width) // 2
    y = (size - fitted.height) // 2
    canvas.paste(fitted, (x, y), fitted)
    return canvas


_SOURCE_ART: dict[str, Image.Image] = {}


def _source_art(kind: str) -> Image.Image | None:
    cached = _SOURCE_ART.get(kind)
    if cached is not None:
        return cached
    path = SOURCE_APP if kind == "app" else SOURCE_FILE
    if not path.is_file():
        return None
    art = _knockout_guide_backdrop(Image.open(path))
    _SOURCE_ART[kind] = art
    return art


def render_windows_app(size: int, *, compact: bool | None = None) -> Image.Image:
    art = _source_art("app")
    if art is not None:
        return _fit_artwork(art, size)
    compact = size <= 48 if compact is None else compact
    plate = _vertical_gradient(size, WIN_TOP, WIN_BOT)
    mask = _squircle_mask(size, 0.225)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas = _paste_masked(canvas, plate, mask)
    draw = ImageDraw.Draw(canvas)
    _draw_brand_mark(
        draw,
        size,
        compact=compact,
        doc_fill=(255, 255, 255),
        doc_fold=(252, 214, 218),
        mark_fill=WIN_BOT,
        text_fill=(255, 255, 255),
        subtitle="PDF EDITOR",
    )
    canvas.putalpha(ImageChops_darker_alpha(canvas, mask))
    return canvas


def ImageChops_darker_alpha(image: Image.Image, mask: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    return Image.fromarray(np.minimum(np.array(alpha), np.array(mask.convert("L"))), "L")


def render_macos_app(size: int, *, compact: bool | None = None) -> Image.Image:
    return render_windows_app(size, compact=compact)


def _draw_block_t(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    width = x1 - x0
    height = y1 - y0
    cx = (x0 + x1) / 2
    top = y0 + max(1, int(height * 0.16))
    bar_h = max(2, int(height * 0.13))
    bar_w = max(5, int(width * 0.58))
    stem_w = max(2, int(width * 0.20))
    stem_h = max(5, int(height * 0.46))
    left = int(round(cx - bar_w / 2))
    draw.rectangle((left, top, left + bar_w - 1, top + bar_h - 1), fill=fill)
    stem_x = int(round(cx - stem_w / 2))
    draw.rectangle((stem_x, top, stem_x + stem_w - 1, top + stem_h - 1), fill=fill)


def render_windows_file(size: int, *, compact: bool | None = None) -> Image.Image:
    art = _source_art("file")
    if art is not None:
        return _fit_artwork(art, size)
    compact = size <= 48 if compact is None else compact
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    pad = 1 if size <= 24 else max(1, size // 16)
    inset = 1 if size <= 24 else size // 8
    box = (pad + inset, pad, size - pad - max(1, inset // 2), size - pad)
    if size <= 24:
        draw.rectangle(box, fill=WIN_FILE, outline=WIN_FILE_EDGE)
    else:
        _draw_document(
            draw,
            box,
            fill=WIN_FILE,
            fold_fill=WIN_FILE_FOLD,
            outline=WIN_FILE_EDGE,
        )
    x0, y0, x1, y1 = box
    if compact:
        _draw_block_t(draw, box, (255, 255, 255))
        return canvas
    mid_y = y0 + int((y1 - y0) * 0.40)
    t_font = _font(max(10, int(size * 0.36)), heavy=True)
    _center_text(draw, "T", mid_y, t_font, (255, 255, 255), size)
    sub_font = _font(max(8, int(size * 0.12)), heavy=True)
    _center_text(draw, "PDF", y0 + int((y1 - y0) * 0.78), sub_font, (255, 255, 255), size)
    return canvas


def render_macos_file(size: int, *, compact: bool | None = None) -> Image.Image:
    return render_windows_file(size, compact=compact)


def _size_set(renderer, sizes: tuple[int, ...]) -> list[Image.Image]:
    return [renderer(size) for size in sizes]


def _rgba_to_ico_dib(image: Image.Image) -> bytes:
    import struct

    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = list(rgba.getdata())
    xor = bytearray()
    for y in range(height - 1, -1, -1):
        for red, green, blue, alpha in pixels[y * width : (y + 1) * width]:
            xor.extend((blue, green, red, alpha))
    and_row = ((width + 31) // 32) * 4
    header = struct.pack(
        "<IIIHHIIIIII",
        40,
        width,
        height * 2,
        1,
        32,
        0,
        len(xor) + and_row * height,
        0,
        0,
        0,
        0,
    )
    return header + xor + bytes(and_row * height)


def save_multi_size_ico(path: Path, images: list[Image.Image]) -> None:
    import struct

    payloads: list[tuple[int, int, bytes]] = []
    for image in images:
        bitmap = image.convert("RGBA")
        payloads.append((bitmap.width, bitmap.height, _rgba_to_ico_dib(bitmap)))

    header = struct.pack("<HHH", 0, 1, len(payloads))
    offset = 6 + 16 * len(payloads)
    entries = bytearray()
    blobs = bytearray()
    for width, height, data in payloads:
        stored_w = 0 if width >= 256 else width
        stored_h = 0 if height >= 256 else height
        entries.extend(
            struct.pack("<BBBBHHII", stored_w, stored_h, 0, 0, 1, 32, len(data), offset)
        )
        blobs.extend(data)
        offset += len(data)
    path.write_bytes(header + entries + blobs)


_ICNS_TYPES = {
    16: b"icp4",
    32: b"icp5",
    64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
    1024: b"ic10",
}


def save_icns(path: Path, renderer) -> bool:
    import io
    import struct

    chunks = bytearray()
    for size in _ICNS_PIXELS:
        icon_type = _ICNS_TYPES.get(size)
        if icon_type is None:
            continue
        buffer = io.BytesIO()
        renderer(size).convert("RGBA").save(buffer, format="PNG")
        payload = buffer.getvalue()
        chunks.extend(icon_type)
        chunks.extend(struct.pack(">I", 8 + len(payload)))
        chunks.extend(payload)
    data = b"icns" + struct.pack(">I", 8 + len(chunks)) + chunks
    path.write_bytes(data)
    return path.is_file()


def render_branding_assets() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MASTER_DIR.mkdir(parents=True, exist_ok=True)

    win_app = render_windows_app(MASTER_SIZE, compact=False)
    win_file = render_windows_file(MASTER_SIZE, compact=False)

    win_app.save(MASTER_DIR / "app_icon_windows.png")
    win_app.save(MASTER_DIR / "app_icon_macos.png")
    win_file.save(MASTER_DIR / "pdf_file_icon_windows.png")
    win_file.save(MASTER_DIR / "pdf_file_icon_macos.png")

    logo = win_app.convert("RGBA")
    logo_box = logo.getbbox()
    if logo_box is not None:
        logo = logo.crop(logo_box)
    logo.save(OUT_DIR / "app_logo.png")
    logo.save(OUT_DIR / "app_logo_macos.png")
    win_app.resize((256, 256), Image.Resampling.LANCZOS).save(OUT_DIR / "app_icon.png")
    win_app.resize((256, 256), Image.Resampling.LANCZOS).save(OUT_DIR / "app_icon_macos.png")
    win_file.resize((256, 256), Image.Resampling.LANCZOS).save(OUT_DIR / "pdf_file_icon_macos.png")

    save_multi_size_ico(OUT_DIR / "app_icon.ico", _size_set(render_windows_app, _ICO_SIZES))
    save_multi_size_ico(OUT_DIR / "pdf_file_icon.ico", _size_set(render_windows_file, _ICO_SIZES))

    app_icns = save_icns(OUT_DIR / "app_icon.icns", render_windows_app)
    file_icns = save_icns(OUT_DIR / "pdf_file_icon.icns", render_windows_file)
    print(f"saved brand icons in {OUT_DIR}")
    if app_icns:
        print(f"saved {OUT_DIR / 'app_icon.icns'}")
    if file_icns:
        print(f"saved {OUT_DIR / 'pdf_file_icon.icns'}")


def main() -> None:
    render_branding_assets()


if __name__ == "__main__":
    main()
