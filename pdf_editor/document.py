"""PDF document model backed by PyMuPDF."""

from __future__ import annotations

import io
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import fitz

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_FILE_FILTER = (
    "지원 파일 (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp);;"
    "PDF (*.pdf);;"
    "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp);;"
    "모든 파일 (*.*)"
)


@dataclass(frozen=True)
class SearchHit:
    page_index: int
    rect: fitz.Rect


@dataclass(frozen=True)
class ReduceSizeOptions:
    """Settings for PDF size reduction."""

    preset: str = "balanced"
    jpeg_quality: int = 50
    max_dpi: int = 150
    image_size_percent: int = 50
    geometry_mode: str = "both"
    grayscale: bool = False
    monochrome: bool = False


GEOMETRY_MODE_BOTH = "both"
GEOMETRY_MODE_PAGE_ONLY = "page_only"
GEOMETRY_MODE_CONTENT_ONLY = "content_only"

_PDF_NUMBER = rb"-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"

_LEADING_UNIFORM_SCALE_RE = re.compile(
    rb"^\s*q\s+(" + _PDF_NUMBER + rb")\s+0\s+0\s+"
    rb"(" + _PDF_NUMBER + rb")\s+0\s+0\s+cm\s*",
    re.DOTALL,
)
_LEADING_PUBLISHER_FLIP_RE = re.compile(
    rb"^\s*(" + _PDF_NUMBER + rb")\s+0\s+0\s+"
    rb"(" + _PDF_NUMBER + rb")\s+0\s+(" + _PDF_NUMBER + rb")\s+cm\s*",
    re.DOTALL,
)
_LEADING_RASTER_STRETCH_RE = re.compile(
    rb"^\s*q\s+(" + _PDF_NUMBER + rb")\s+(" + _PDF_NUMBER + rb")\s+("
    + _PDF_NUMBER + rb")\s+(" + _PDF_NUMBER + rb")\s+("
    + _PDF_NUMBER + rb")\s+(" + _PDF_NUMBER + rb")\s+cm(\s*.*)$",
    re.DOTALL,
)
_IMAGE_DO_CM_RE = re.compile(
    rb"(" + _PDF_NUMBER + rb")\s+(" + _PDF_NUMBER + rb")\s+("
    + _PDF_NUMBER + rb")\s+(" + _PDF_NUMBER + rb")\s+("
    + _PDF_NUMBER + rb")\s+(" + _PDF_NUMBER + rb")\s+cm\s*/(\w+)\s+Do",
)
_FULLPAGE_RASTER_COVERAGE = 0.65
_PROFILE_SAMPLE_PAGES = 20
_MAX_UNDO_LEVELS = 50


MIN_IMAGE_DPI = 24

PDF_SAVE_KWARGS: dict[str, object] = {
    "garbage": 4,
    "deflate": True,
    "use_objstms": True,
}


PRESET_OPTIONS: dict[str, ReduceSizeOptions] = {
    "maximum": ReduceSizeOptions(
        preset="maximum",
        jpeg_quality=55,
        max_dpi=72,
        grayscale=True,
    ),
    "balanced": ReduceSizeOptions(
        preset="balanced",
        jpeg_quality=50,
        max_dpi=150,
        image_size_percent=50,
        grayscale=False,
    ),
    "high": ReduceSizeOptions(
        preset="high",
        jpeg_quality=92,
        max_dpi=300,
        grayscale=False,
    ),
}


def format_file_size(num_bytes: int) -> str:
    mb = num_bytes / (1024 * 1024)
    if mb >= 0.1:
        return f"{mb:.1f} MB"
    return f"{num_bytes / 1024:.0f} KB"


CONTENT_KIND_EMPTY = "empty"
CONTENT_KIND_PUBLISHER_FLIP = "publisher_flip"
CONTENT_KIND_RASTER_STRETCH = "raster_stretch"
CONTENT_KIND_UNIFORM = "uniform"
CONTENT_KIND_PLAIN = "plain"

# Reduce-time geometry cases handled in ``scale_content_stream_for_reduce``:
# - publisher_flip: ``sx 0 0 -sy 0 ty cm`` (출판/교과서 Y축 뒤집기) → scale + ty together
# - raster_stretch: ``q sx 0 0 sy e f cm /Img Do`` (풀페이지·다중 레이어 래스터) → scale all cm/Do
# - uniform: ``q s 0 0 s 0 0 cm`` (인쇄용 내장 배율) → replace leading scale, no nest
# - plain: vector/text or unknown → wrap once in BOTH/CONTENT_ONLY; PAGE_ONLY mediabox only
# - empty: ``q`` / ``Q`` wrappers → never modify (multi-stream pages stay intact)
#
# Image cases handled in resample/recompress:
# - /SMask soft masks → always ``replace_image`` (never manual /Mask rewrite)
# - skip when effective DPI already <= target and dimensions unchanged
# - JBIG2 / undecodable images → skip safely via ``_safe_pixmap_from_xref``

_CONTENT_KIND_PRIORITY = (
    CONTENT_KIND_PUBLISHER_FLIP,
    CONTENT_KIND_RASTER_STRETCH,
    CONTENT_KIND_UNIFORM,
    CONTENT_KIND_PLAIN,
    CONTENT_KIND_EMPTY,
)


@dataclass(frozen=True)
class PageReduceGeometry:
    """Per-page geometry hints collected before scaling."""

    is_fullpage_raster: bool
    content_kinds: tuple[str, ...]

    @property
    def dominant_kind(self) -> str:
        for kind in _CONTENT_KIND_PRIORITY:
            if kind in self.content_kinds:
                return kind
        return CONTENT_KIND_PLAIN

    @property
    def has_transform_stream(self) -> bool:
        return any(
            kind
            for kind in self.content_kinds
            if kind
            not in (
                CONTENT_KIND_EMPTY,
                CONTENT_KIND_PLAIN,
            )
        )


@dataclass(frozen=True)
class DocumentReduceProfile:
    """Heuristics for publisher / raster PDFs that need careful geometry scaling."""

    embedded_uniform_scale: float | None = None
    publisher_flip_scale: float | None = None
    fullpage_raster_ratio: float = 0.0

    @property
    def prefers_page_only(self) -> bool:
        if self.fullpage_raster_ratio >= 0.5:
            return True
        if self.publisher_flip_scale is not None:
            return True
        if self.embedded_uniform_scale is not None:
            return True
        return False


class PdfDocument:
    """In-memory PDF with page insert, delete, rotate, and export operations."""

    def __init__(self) -> None:
        self._doc = fitz.open()
        self._source_path: str | None = None
        self._modified = False
        self._render_pause_depth = 0
        self._undo_stack: list[bytes] = []
        self._redo_stack: list[bytes] = []
        self._restoring_history = False

    @property
    def rendering_paused(self) -> bool:
        return self._render_pause_depth > 0

    def pause_rendering(self) -> None:
        self._render_pause_depth += 1

    def resume_rendering(self) -> None:
        self._render_pause_depth = max(0, self._render_pause_depth - 1)

    @property
    def page_count(self) -> int:
        return len(self._doc)

    @property
    def source_path(self) -> str | None:
        return self._source_path

    @property
    def modified(self) -> bool:
        return self._modified

    @property
    def display_name(self) -> str:
        if self._source_path:
            return os.path.basename(self._source_path)
        return "새 문서"

    def open_file(self, path: str) -> None:
        path = str(Path(path))
        ext = Path(path).suffix.lower()
        if ext in PDF_EXTENSIONS:
            pdf_bytes = Path(path).read_bytes()
            new_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            del pdf_bytes
            self._source_path = path
        elif ext in IMAGE_EXTENSIONS:
            new_doc = PdfDocument._open_image_as_document(path)
            self._source_path = None
        else:
            raise ValueError(f"지원하지 않는 파일 형식입니다: {ext}")
        self._doc.close()
        self._doc = new_doc
        self._modified = False
        self.clear_history()

    @staticmethod
    def _open_image_as_document(path: str) -> fitz.Document:
        img_doc = fitz.open(path)
        try:
            pdf_bytes = img_doc.convert_to_pdf()
        finally:
            img_doc.close()
        return fitz.open(stream=pdf_bytes, filetype="pdf")

    def new_document(self) -> None:
        self._doc.close()
        self._doc = fitz.open()
        self._source_path = None
        self._modified = False
        self.clear_history()

    def clear_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def _record_undo_checkpoint(self) -> None:
        if self._restoring_history:
            return
        if len(self._doc) == 0:
            return
        self._undo_stack.append(self.save_to_bytes())
        if len(self._undo_stack) > _MAX_UNDO_LEVELS:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore_from_snapshot(self, payload: bytes) -> None:
        self._restoring_history = True
        try:
            self._doc.close()
            self._doc = fitz.open(stream=payload, filetype="pdf")
            self._touch()
        finally:
            self._restoring_history = False

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self.save_to_bytes())
        payload = self._undo_stack.pop()
        self._restore_from_snapshot(payload)
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self.save_to_bytes())
        payload = self._redo_stack.pop()
        self._restore_from_snapshot(payload)
        return True

    def _saving_in_place(self, target: str) -> bool:
        if not self._source_path:
            return False
        return Path(target).resolve() == Path(self._source_path).resolve()

    def _staging_path(self, target: Path) -> Path:
        """원본과 같은 폴더에 쓸 중간 저장 경로 (예: report (1).pdf)."""
        parent = target.parent
        stem = target.stem
        suffix = target.suffix
        n = 1
        while True:
            candidate = parent / f"{stem} ({n}){suffix}"
            if not candidate.exists():
                return candidate
            n += 1

    def save(self, path: str | None = None) -> str:
        target = path or self._source_path
        if not target:
            raise ValueError("저장 경로가 지정되지 않았습니다.")
        target = str(Path(target))

        if self._saving_in_place(target):
            target_path = Path(target)
            staging = self._staging_path(target_path)
            try:
                self._doc.save(str(staging), **PDF_SAVE_KWARGS)
                os.replace(str(staging), target)
            except Exception:
                staging.unlink(missing_ok=True)
                raise
        else:
            self._doc.save(target, **PDF_SAVE_KWARGS)

        self._source_path = target
        self._modified = False
        return target

    def save_to_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self._doc.save(buffer, **PDF_SAVE_KWARGS)
        return buffer.getvalue()

    @staticmethod
    def _serialize_doc_bytes(doc: fitz.Document) -> bytes:
        buffer = io.BytesIO()
        doc.save(buffer, **PDF_SAVE_KWARGS)
        return buffer.getvalue()

    @staticmethod
    def _measure_doc_bytes(doc: fitz.Document) -> int:
        return len(PdfDocument._serialize_doc_bytes(doc))

    def current_file_size(self) -> int:
        return len(self.save_to_bytes())

    def _clone_document(self) -> fitz.Document:
        return fitz.open(stream=self.save_to_bytes(), filetype="pdf")

    @staticmethod
    def _safe_pixmap_from_xref(doc: fitz.Document, xref: int) -> fitz.Pixmap | None:
        """Decode an embedded image; return None when MuPDF cannot read it (e.g. JBIG2)."""
        try:
            pix = fitz.Pixmap(doc, xref)
        except Exception:
            return None
        if pix.colorspace is None:
            return None
        return pix

    @staticmethod
    def _to_monochrome_pixmap(pix: fitz.Pixmap, threshold: int = 128) -> fitz.Pixmap:
        gray = fitz.Pixmap(fitz.csGRAY, pix)
        samples = bytearray(gray.samples)
        for index in range(len(samples)):
            samples[index] = 255 if samples[index] >= threshold else 0
        return fitz.Pixmap(fitz.csGRAY, gray.width, gray.height, bytes(samples), False)

    @staticmethod
    def _collect_image_smask_map(doc: fitz.Document) -> dict[int, int]:
        """Map each image xref to its mask xref (/Mask entry), if present."""
        smasks: dict[int, int] = {}
        for page in doc:
            try:
                images = page.get_images(full=True)
            except Exception:
                continue
            for img in images:
                xref = img[0]
                mask_xref = int(img[1]) if len(img) > 1 else 0
                if mask_xref > 0:
                    smasks[xref] = mask_xref
        return smasks

    @staticmethod
    def _pixmap_colorspace_name(pix: fitz.Pixmap) -> str:
        if pix.colorspace is None:
            return "DeviceRGB"
        if pix.colorspace.n == 1:
            return "DeviceGray"
        return "DeviceRGB"

    @staticmethod
    def _replace_image_stream_preserving_mask(
        doc: fitz.Document,
        xref: int,
        *,
        stream: bytes,
        width: int,
        height: int,
        mask_xref: int,
        colorspace: str,
    ) -> None:
        """Replace an image stream while keeping its PDF soft-mask reference."""
        pdf_object = (
            f"<< /Type /XObject /Subtype /Image"
            f" /Width {width} /Height {height}"
            f" /ColorSpace /{colorspace} /BitsPerComponent 8"
            f" /Filter /DCTDecode"
            f" /SMask {mask_xref} 0 R"
            f" /Length {len(stream)} >>"
        )
        doc.update_object(xref, pdf_object)
        doc.update_stream(xref, stream)

    @staticmethod
    def _replace_image_jpeg_preserving_mask(
        doc: fitz.Document,
        xref: int,
        *,
        stream: bytes,
        width: int,
        height: int,
        mask_xref: int,
    ) -> None:
        """Replace an image with gray JPEG while keeping its PDF /Mask reference."""
        PdfDocument._replace_image_stream_preserving_mask(
            doc,
            xref,
            stream=stream,
            width=width,
            height=height,
            mask_xref=mask_xref,
            colorspace="DeviceGray",
        )

    @staticmethod
    def _convert_embedded_images_color_mode(
        doc: fitz.Document,
        options: ReduceSizeOptions,
    ) -> None:
        """Convert embedded color images to gray or monochrome; text is untouched."""
        if not (options.grayscale or options.monochrome):
            return

        quality = max(1, min(100, options.jpeg_quality))
        processed: set[int] = set()
        for page in doc:
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in processed:
                    continue
                processed.add(xref)
                pix = PdfDocument._safe_pixmap_from_xref(doc, xref)
                if pix is None:
                    continue

                converted: fitz.Pixmap | None = None
                try:
                    if options.monochrome:
                        if pix.colorspace.n == 1 and pix.samples:
                            converted = pix
                        else:
                            converted = PdfDocument._to_monochrome_pixmap(pix)
                    elif pix.colorspace.n == 1:
                        continue
                    else:
                        converted = fitz.Pixmap(fitz.csGRAY, pix)

                    stream = converted.tobytes("jpeg", jpg_quality=quality)
                    page.replace_image(xref, stream=stream)
                except Exception:
                    continue
                finally:
                    converted = None
                    pix = None

    @staticmethod
    def _resample_single_image(
        doc: fitz.Document,
        xref: int,
        display_rect: fitz.Rect,
        page_index: int,
        *,
        target_dpi: int,
        jpeg_quality: int,
        min_effective_dpi: float | None = None,
        skip_if_display_dpi_met: bool = True,
    ) -> bool:
        """Downsample one embedded image to its on-page display size; return True if updated."""
        if display_rect.is_empty:
            return False

        target_w = max(1, int(display_rect.width * target_dpi / 72))
        target_h = max(1, int(display_rect.height * target_dpi / 72))

        pix = PdfDocument._safe_pixmap_from_xref(doc, xref)
        if pix is None:
            return False

        scaled: fitz.Pixmap | None = None
        try:
            effective_dpi = PdfDocument._image_effective_dpi(pix, display_rect)
            if (
                min_effective_dpi is not None
                and effective_dpi > 0
                and effective_dpi < min_effective_dpi
            ):
                return False
            scaled = PdfDocument._downsample_pixmap(pix, target_w, target_h)
            resized = scaled.width < pix.width or scaled.height < pix.height
            if (
                skip_if_display_dpi_met
                and not resized
                and effective_dpi <= target_dpi
            ):
                return False
            stream = scaled.tobytes("jpeg", jpg_quality=jpeg_quality)
            doc[page_index].replace_image(xref, stream=stream)
            return True
        except Exception:
            return False
        finally:
            scaled = None
            pix = None

    @staticmethod
    def _recompress_images_individually(
        doc: fitz.Document,
        options: ReduceSizeOptions,
        *,
        target_dpi: int,
        dpi_threshold: int | None,
    ) -> None:
        """Recompress each embedded image; skip images that cannot be decoded."""
        quality = max(1, min(100, options.jpeg_quality))
        targets = PdfDocument._collect_image_resize_targets(doc)

        for xref, (display_rect, page_index, smask) in targets.items():
            PdfDocument._resample_single_image(
                doc,
                xref,
                display_rect,
                page_index,
                target_dpi=target_dpi,
                jpeg_quality=quality,
                min_effective_dpi=float(dpi_threshold)
                if dpi_threshold is not None
                else None,
                skip_if_display_dpi_met=False,
            )

    @staticmethod
    def _rewrite_images_preserve_text(
        doc: fitz.Document,
        options: ReduceSizeOptions,
        *,
        target_dpi: int,
        dpi_threshold: int | None,
    ) -> None:
        """Recompress embedded images only; do not recolor or outline text."""
        bulk_ok = False
        try:
            doc.rewrite_images(
                dpi_threshold=dpi_threshold,
                dpi_target=target_dpi,
                quality=options.jpeg_quality,
                set_to_gray=False,
            )
            bulk_ok = True
        except Exception:
            bulk_ok = False
        if not bulk_ok:
            PdfDocument._recompress_images_individually(
                doc,
                options,
                target_dpi=target_dpi,
                dpi_threshold=dpi_threshold,
            )
        PdfDocument._convert_embedded_images_color_mode(doc, options)

    @staticmethod
    def _apply_post_processing(doc: fitz.Document) -> None:
        doc.set_metadata({})
        if hasattr(doc, "del_xml_metadata"):
            doc.del_xml_metadata()
        try:
            doc.subset_fonts()
        except Exception:
            pass

    @staticmethod
    def _collect_image_resize_targets(
        doc: fitz.Document,
    ) -> dict[int, tuple[fitz.Rect, int, int]]:
        """Map each image xref to its largest display rect, page index, and smask."""
        targets: dict[int, tuple[fitz.Rect, int, int]] = {}
        largest_area: dict[int, float] = {}
        for page_index in range(len(doc)):
            try:
                page = doc[page_index]
                images = page.get_images(full=True)
            except Exception:
                continue
            for img in images:
                xref = img[0]
                smask = int(img[1]) if len(img) > 1 else 0
                try:
                    rects = page.get_image_rects(xref)
                except Exception:
                    continue
                for rect in rects:
                    area = rect.width * rect.height
                    if area > largest_area.get(xref, 0.0):
                        largest_area[xref] = area
                        targets[xref] = (rect, page_index, smask)
        return targets

    @staticmethod
    def _image_effective_dpi(pix: fitz.Pixmap, display_rect: fitz.Rect) -> float:
        if display_rect.width <= 0 or display_rect.height <= 0:
            return 0.0
        return min(
            pix.width / display_rect.width * 72,
            pix.height / display_rect.height * 72,
        )

    @staticmethod
    def _downsample_pixmap(pix: fitz.Pixmap, target_w: int, target_h: int) -> fitz.Pixmap:
        scale = min(target_w / pix.width, target_h / pix.height, 1.0)
        if scale >= 1.0:
            return pix
        new_w = max(1, int(pix.width * scale))
        new_h = max(1, int(pix.height * scale))
        if pix.alpha:
            rgb = fitz.Pixmap(fitz.csRGB, pix)
            return fitz.Pixmap(rgb, new_w, new_h)
        return fitz.Pixmap(pix, new_w, new_h)

    @staticmethod
    def _compact_document(doc: fitz.Document) -> fitz.Document:
        """Drop orphaned objects and return a clean in-memory copy."""
        payload = doc.tobytes(**PDF_SAVE_KWARGS)
        return fitz.open(stream=payload, filetype="pdf")

    @staticmethod
    def _resample_effective_dpi(max_dpi: int, jpeg_quality: int) -> int:
        target_dpi = max(MIN_IMAGE_DPI, max_dpi)
        if jpeg_quality <= 10:
            return max(MIN_IMAGE_DPI, int(target_dpi * 0.8))
        if jpeg_quality <= 20:
            return max(MIN_IMAGE_DPI, int(target_dpi * 0.9))
        return target_dpi

    @staticmethod
    def _resample_embedded_images_to_display_size(
        doc: fitz.Document,
        *,
        max_dpi: int,
        jpeg_quality: int,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Downsample images to match on-page display size; never upscale."""
        target_dpi = PdfDocument._resample_effective_dpi(max_dpi, jpeg_quality)
        quality = max(1, min(100, jpeg_quality))
        targets = PdfDocument._collect_image_resize_targets(doc)
        total = len(targets)
        if total == 0:
            return

        progress_stride = max(1, total // 50)
        for index, (xref, (display_rect, page_index, smask)) in enumerate(
            targets.items(), start=1
        ):
            if image_progress is not None and (
                index == 1 or index == total or index % progress_stride == 0
            ):
                image_progress(index, total)

            PdfDocument._resample_single_image(
                doc,
                xref,
                display_rect,
                page_index,
                target_dpi=target_dpi,
                jpeg_quality=quality,
            )

    @staticmethod
    def _parse_leading_uniform_scale(content: bytes) -> tuple[float | None, bytes]:
        match = _LEADING_UNIFORM_SCALE_RE.match(content)
        if not match:
            return None, content
        sx = float(match.group(1))
        sy = float(match.group(2))
        if abs(sx - sy) > 1e-4:
            return None, content
        return sx, content[match.end() :]

    @staticmethod
    def _format_uniform_scale_prefix(scale: float) -> bytes:
        return f"q {scale:g} 0 0 {scale:g} 0 0 cm\n".encode("ascii")

    @staticmethod
    def _parse_leading_publisher_flip(content: bytes) -> tuple[float, float, bytes] | None:
        """Parse ``sx 0 0 -sy 0 ty cm`` (Y-flip publisher export)."""
        match = _LEADING_PUBLISHER_FLIP_RE.match(content)
        if not match:
            return None
        sx = float(match.group(1))
        sy = float(match.group(2))
        ty = float(match.group(3))
        if sx <= 0 or sy >= 0:
            return None
        if abs(abs(sx) - abs(sy)) > 1e-3:
            return None
        return abs(sx), ty, content[match.end() :]

    @staticmethod
    def _parse_leading_raster_stretch(content: bytes) -> tuple[float, float, bytes] | None:
        """Parse ``q sx 0 0 sy e f cm ...`` used by full-page raster exports."""
        match = _LEADING_RASTER_STRETCH_RE.match(content)
        if not match:
            return None
        sx = float(match.group(1))
        sy = float(match.group(4))
        b = float(match.group(2))
        c = float(match.group(3))
        if sx <= 0 or sy <= 0:
            return None
        if abs(b) > 1e-4 or abs(c) > 1e-4:
            return None
        return sx, sy, match.group(7)

    @staticmethod
    def _format_raster_stretch_prefix(sx: float, sy: float) -> bytes:
        return f"q {sx:g} 0 0 {sy:g} 0 0 cm".encode("ascii")

    @staticmethod
    def _scale_image_do_matrices(content: bytes, factor: float) -> bytes | None:
        """Scale every ``a b c d e f cm /Name Do`` matrix (multi-layer raster exports)."""
        if abs(factor - 1.0) < 1e-6:
            return None
        if not _IMAGE_DO_CM_RE.search(content):
            return None

        def repl(match: re.Match[bytes]) -> bytes:
            nums = [float(match.group(index)) * factor for index in range(1, 7)]
            matrix = " ".join(f"{value:g}" for value in nums).encode("ascii")
            name = match.group(7).decode("ascii")
            return matrix + f" cm /{name} Do".encode("ascii")

        return _IMAGE_DO_CM_RE.sub(repl, content)

    @staticmethod
    def _stream_is_image_do_overlay(content: bytes) -> bool:
        """True when the stream only places images via ``cm /X Do`` (Canon overlay PDFs)."""
        if PdfDocument._is_auxiliary_content(content):
            return False
        stripped = re.sub(rb"%[^\n]*", b"", content)
        if not _IMAGE_DO_CM_RE.search(stripped):
            return False
        if re.search(rb"\b(Tj|TJ|'|\")", stripped):
            return False
        return True

    @staticmethod
    def _apply_raster_stretch_scale(content: bytes, factor: float) -> bytes | None:
        scaled = PdfDocument._scale_image_do_matrices(content, factor)
        if scaled is not None:
            return scaled
        parsed = PdfDocument._parse_leading_raster_stretch(content)
        if parsed is None:
            return None
        sx, sy, rest = parsed
        return PdfDocument._format_raster_stretch_prefix(sx * factor, sy * factor) + rest

    @staticmethod
    def _parse_content_transforms(
        content: bytes,
    ) -> tuple[float | None, float | None, float | None, bytes]:
        """Return optional ``q``-scale, flip-scale, flip-ty, and remainder."""
        rest = content
        uniform: float | None = None
        leading_uniform, after_uniform = PdfDocument._parse_leading_uniform_scale(rest)
        if leading_uniform is not None:
            uniform = leading_uniform
            rest = after_uniform
        flip = PdfDocument._parse_leading_publisher_flip(rest)
        if flip is not None:
            flip_scale, flip_ty, rest = flip
            return uniform, flip_scale, flip_ty, rest
        return uniform, None, None, content

    @staticmethod
    def _format_publisher_flip_prefix(scale: float, ty: float) -> bytes:
        return f"{scale:g} 0 0 {-scale:g} 0 {ty:g} cm\n".encode("ascii")

    @staticmethod
    def _format_content_transforms(
        *,
        uniform: float | None,
        flip_scale: float | None,
        flip_ty: float | None,
        rest: bytes,
    ) -> bytes:
        parts: list[bytes] = []
        if uniform is not None and abs(uniform - 1.0) > 1e-6:
            parts.append(PdfDocument._format_uniform_scale_prefix(uniform))
        if flip_scale is not None and flip_ty is not None:
            parts.append(PdfDocument._format_publisher_flip_prefix(flip_scale, flip_ty))
        parts.append(rest)
        return b"".join(parts)

    @staticmethod
    def _apply_content_scale_to_stream(
        content: bytes,
        factor: float,
        *,
        flip_ty_only: bool = False,
    ) -> bytes:
        """Apply *factor* once without nesting duplicate ``cm`` transforms."""
        if abs(factor - 1.0) < 1e-6:
            return content

        uniform, flip_scale, flip_ty, rest = PdfDocument._parse_content_transforms(content)
        if flip_scale is not None and flip_ty is not None:
            if flip_ty_only:
                return PdfDocument._format_content_transforms(
                    uniform=uniform,
                    flip_scale=flip_scale,
                    flip_ty=flip_ty * factor,
                    rest=rest,
                )
            return PdfDocument._format_content_transforms(
                uniform=uniform * factor if uniform is not None else None,
                flip_scale=flip_scale * factor,
                flip_ty=flip_ty * factor,
                rest=rest,
            )

        if uniform is not None:
            return PdfDocument._format_uniform_scale_prefix(uniform * factor) + rest
        prefix = PdfDocument._format_uniform_scale_prefix(factor)
        return prefix + content + b"\nQ"

    @staticmethod
    def _page_is_fullpage_raster(doc: fitz.Document, page_index: int) -> bool:
        page = doc[page_index]
        images = page.get_images(full=True)
        if len(images) != 1:
            return False
        xref = images[0][0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            return False
        if not rects:
            return False
        page_area = page.mediabox.width * page.mediabox.height
        if page_area <= 0:
            return False
        largest = max(rects, key=lambda rect: rect.width * rect.height)
        if (largest.width * largest.height) / page_area >= _FULLPAGE_RASTER_COVERAGE:
            return True

        try:
            info = doc.extract_image(xref)
        except Exception:
            return False
        native_w = int(info.get("width", 0))
        native_h = int(info.get("height", 0))
        if native_w < 640 or native_h < 640:
            return False
        page_ratio = page.mediabox.width / page.mediabox.height
        native_ratio = native_w / native_h
        if abs(page_ratio - native_ratio) > 0.12:
            return False
        return native_w * native_h >= 900_000

    @staticmethod
    def _profile_sample_page_indices(doc: fitz.Document) -> list[int]:
        page_count = len(doc)
        if page_count <= _PROFILE_SAMPLE_PAGES:
            return list(range(page_count))
        step = max(1, page_count // _PROFILE_SAMPLE_PAGES)
        indices = list(range(0, page_count, step))
        if page_count - 1 not in indices:
            indices.append(page_count - 1)
        return indices[:_PROFILE_SAMPLE_PAGES]

    @staticmethod
    def analyze_reduce_profile(doc: fitz.Document) -> DocumentReduceProfile:
        uniform_counts: dict[float, int] = {}
        flip_counts: dict[float, int] = {}
        raster_hits = 0
        samples = 0

        for page_index in PdfDocument._profile_sample_page_indices(doc):
            samples += 1
            page_geometry = PdfDocument.analyze_page_reduce_geometry(doc, page_index)
            if page_geometry.is_fullpage_raster:
                raster_hits += 1

            for xref in PdfDocument._page_content_xrefs(doc, page_index):
                try:
                    content = doc.xref_stream(xref)
                except Exception:
                    continue
                kind = PdfDocument.classify_content_stream(content)
                if kind == CONTENT_KIND_UNIFORM:
                    leading, _ = PdfDocument._parse_leading_uniform_scale(content)
                    if leading is not None and abs(leading - 1.0) >= 0.01:
                        key = round(leading, 4)
                        uniform_counts[key] = uniform_counts.get(key, 0) + 1
                elif kind == CONTENT_KIND_PUBLISHER_FLIP:
                    _, flip_scale, _, _ = PdfDocument._parse_content_transforms(content)
                    if flip_scale is not None:
                        key = round(flip_scale, 4)
                        flip_counts[key] = flip_counts.get(key, 0) + 1

        embedded_uniform = (
            max(uniform_counts, key=uniform_counts.get) if uniform_counts else None
        )
        publisher_flip = max(flip_counts, key=flip_counts.get) if flip_counts else None
        raster_ratio = raster_hits / samples if samples else 0.0
        return DocumentReduceProfile(
            embedded_uniform_scale=embedded_uniform,
            publisher_flip_scale=publisher_flip,
            fullpage_raster_ratio=raster_ratio,
        )

    def reduce_profile(self) -> DocumentReduceProfile:
        return PdfDocument.analyze_reduce_profile(self._doc)

    @staticmethod
    def sample_embedded_uniform_scale(doc: fitz.Document) -> float | None:
        return PdfDocument.analyze_reduce_profile(doc).embedded_uniform_scale

    def embedded_uniform_scale(self) -> float | None:
        return self.reduce_profile().embedded_uniform_scale

    @staticmethod
    def _page_content_xrefs(doc: fitz.Document, page_index: int) -> list[int]:
        xrefs = doc[page_index].get_contents()
        if not xrefs:
            return []
        if isinstance(xrefs, int):
            return [xrefs]
        return list(dict.fromkeys(xrefs))

    @staticmethod
    def _is_auxiliary_content(content: bytes) -> bool:
        stripped = content.strip()
        if not stripped:
            return True
        if stripped in (b"q", b"Q"):
            return True
        compact = stripped.replace(b"\n", b"").replace(b" ", b"")
        return compact in (b"q", b"Q", b"qQ", b"Qq")

    @staticmethod
    def classify_content_stream(content: bytes) -> str:
        """Classify a single content stream for reduce-time geometry handling."""
        if PdfDocument._is_auxiliary_content(content):
            return CONTENT_KIND_EMPTY
        if PdfDocument._parse_leading_raster_stretch(content) is not None:
            return CONTENT_KIND_RASTER_STRETCH
        if PdfDocument._stream_is_image_do_overlay(content):
            return CONTENT_KIND_RASTER_STRETCH
        _, flip_scale, flip_ty, _ = PdfDocument._parse_content_transforms(content)
        if flip_scale is not None and flip_ty is not None:
            return CONTENT_KIND_PUBLISHER_FLIP
        leading_uniform, _ = PdfDocument._parse_leading_uniform_scale(content)
        if leading_uniform is not None:
            return CONTENT_KIND_UNIFORM
        return CONTENT_KIND_PLAIN

    @staticmethod
    def analyze_page_reduce_geometry(
        doc: fitz.Document,
        page_index: int,
    ) -> PageReduceGeometry:
        kinds: list[str] = []
        for xref in PdfDocument._page_content_xrefs(doc, page_index):
            try:
                content = doc.xref_stream(xref)
            except Exception:
                continue
            kinds.append(PdfDocument.classify_content_stream(content))
        if not kinds:
            kinds = [CONTENT_KIND_PLAIN]
        return PageReduceGeometry(
            is_fullpage_raster=PdfDocument._page_is_fullpage_raster(doc, page_index),
            content_kinds=tuple(dict.fromkeys(kinds)),
        )

    @staticmethod
    def scale_content_stream_for_reduce(
        content: bytes,
        factor: float,
        *,
        geometry_mode: str,
    ) -> bytes | None:
        """Return scaled stream bytes, or ``None`` when the stream should be left unchanged."""
        if abs(factor - 1.0) < 1e-6:
            return None

        kind = PdfDocument.classify_content_stream(content)
        if kind == CONTENT_KIND_EMPTY:
            return None
        if kind == CONTENT_KIND_PUBLISHER_FLIP:
            return PdfDocument._apply_content_scale_to_stream(
                content,
                factor,
                flip_ty_only=False,
            )
        if kind == CONTENT_KIND_RASTER_STRETCH:
            return PdfDocument._apply_raster_stretch_scale(content, factor)
        if kind == CONTENT_KIND_UNIFORM:
            leading_uniform, rest = PdfDocument._parse_leading_uniform_scale(content)
            if leading_uniform is None:
                return None
            return (
                PdfDocument._format_uniform_scale_prefix(leading_uniform * factor) + rest
            )
        if kind == CONTENT_KIND_PLAIN:
            if geometry_mode == GEOMETRY_MODE_PAGE_ONLY:
                if PdfDocument._stream_is_image_do_overlay(content):
                    return PdfDocument._scale_image_do_matrices(content, factor)
                return None
            if geometry_mode in (
                GEOMETRY_MODE_BOTH,
                GEOMETRY_MODE_CONTENT_ONLY,
            ):
                if PdfDocument._stream_is_image_do_overlay(content):
                    return PdfDocument._scale_image_do_matrices(content, factor)
                return PdfDocument._apply_content_scale_to_stream(
                    content,
                    factor,
                    flip_ty_only=False,
                )
            return None
        return None

    @staticmethod
    def _scale_single_page_in_place(
        doc: fitz.Document,
        page_index: int,
        scale: float,
        *,
        geometry_mode: str = GEOMETRY_MODE_BOTH,
        profile: DocumentReduceProfile | None = None,
    ) -> None:
        """Scale page geometry and/or content without nesting duplicate transforms."""
        if abs(scale - 1.0) < 1e-6:
            return
        if geometry_mode not in (
            GEOMETRY_MODE_BOTH,
            GEOMETRY_MODE_PAGE_ONLY,
            GEOMETRY_MODE_CONTENT_ONLY,
        ):
            geometry_mode = GEOMETRY_MODE_BOTH

        page = doc[page_index]
        page_geometry = PdfDocument.analyze_page_reduce_geometry(doc, page_index)

        effective_mode = geometry_mode
        if page_geometry.is_fullpage_raster and geometry_mode == GEOMETRY_MODE_BOTH:
            effective_mode = GEOMETRY_MODE_PAGE_ONLY

        new_rect = fitz.Rect(
            0,
            0,
            max(1.0, round(page.mediabox.width * scale, 4)),
            max(1.0, round(page.mediabox.height * scale, 4)),
        )
        resize_page = effective_mode in (
            GEOMETRY_MODE_BOTH,
            GEOMETRY_MODE_PAGE_ONLY,
        )

        if page.get_contents():
            if not page_geometry.has_transform_stream:
                page.wrap_contents()
            for xref in PdfDocument._page_content_xrefs(doc, page_index):
                try:
                    content = doc.xref_stream(xref)
                except Exception:
                    continue
                updated = PdfDocument.scale_content_stream_for_reduce(
                    content,
                    scale,
                    geometry_mode=effective_mode,
                )
                if updated is not None:
                    doc.update_stream(xref, updated)

        if resize_page:
            page.set_mediabox(new_rect)

    @staticmethod
    def _scale_document_geometry(
        doc: fitz.Document,
        percent: int,
        *,
        geometry_mode: str = GEOMETRY_MODE_BOTH,
        profile: DocumentReduceProfile | None = None,
        page_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Scale each page in place by *percent* (aspect ratio kept, text preserved)."""
        if percent >= 100:
            return
        if profile is None:
            profile = PdfDocument.analyze_reduce_profile(doc)
        scale = percent / 100.0
        page_count = len(doc)
        for index in range(page_count):
            PdfDocument._scale_single_page_in_place(
                doc,
                index,
                scale,
                geometry_mode=geometry_mode,
                profile=profile,
            )
            if page_progress is not None:
                page_progress(index + 1, page_count)

    @staticmethod
    def _apply_geometry_scale(
        doc: fitz.Document,
        options: ReduceSizeOptions,
        *,
        page_progress: Callable[[int, int], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> fitz.Document:
        if options.image_size_percent >= 100:
            return doc
        profile = PdfDocument.analyze_reduce_profile(doc)
        if status_callback is not None:
            status_callback(
                f"페이지 크기를 {options.image_size_percent}%로 조정하는 중..."
            )
        PdfDocument._scale_document_geometry(
            doc,
            options.image_size_percent,
            geometry_mode=options.geometry_mode,
            profile=profile,
            page_progress=page_progress,
        )
        if status_callback is not None:
            status_callback("이미지를 표시 크기에 맞게 조정하는 중...")
        PdfDocument._resample_embedded_images_to_display_size(
            doc,
            max_dpi=options.max_dpi,
            jpeg_quality=options.jpeg_quality,
            image_progress=image_progress,
        )
        return doc

    @staticmethod
    def _compress_document(
        source: fitz.Document,
        options: ReduceSizeOptions,
        *,
        page_progress: Callable[[int, int], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> fitz.Document:
        """Build a reduced copy: recompress → post-process → geometry → resample → compact."""
        target_dpi = max(MIN_IMAGE_DPI, options.max_dpi)
        working = fitz.open(stream=source.tobytes(), filetype="pdf")

        if status_callback is not None:
            if options.grayscale or options.monochrome:
                mode = "단색조" if options.monochrome else "회색조"
                status_callback(
                    f"이미지 재압축 및 {mode} 변환 중... (텍스트는 유지됩니다)"
                )
            else:
                status_callback("이미지 재압축하는 중... (텍스트는 유지됩니다)")
        if options.preset == "high":
            dpi_threshold: int | None = max(target_dpi + 1, 450)
        else:
            # Only downsample images above the DPI cap; never upscale low-res art.
            dpi_threshold = target_dpi + 1
        try:
            PdfDocument._rewrite_images_preserve_text(
                working,
                options,
                target_dpi=target_dpi,
                dpi_threshold=dpi_threshold,
            )
        except Exception:
            if status_callback is not None:
                status_callback(
                    "일부 이미지 재압축을 건너뛰고 나머지 처리를 진행합니다..."
                )

        if status_callback is not None:
            status_callback("마무리 처리 중...")
        PdfDocument._apply_post_processing(working)
        try:
            result = PdfDocument._apply_geometry_scale(
                working,
                options,
                page_progress=page_progress,
                status_callback=status_callback,
                image_progress=image_progress,
            )
            return PdfDocument._compact_document(result)
        finally:
            working.close()

    @staticmethod
    def compress_document_bytes(
        source_bytes: bytes,
        options: ReduceSizeOptions,
        *,
        page_progress: Callable[[int, int], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> fitz.Document:
        """Build a reduced document from a PDF byte snapshot (safe for background threads)."""
        source = fitz.open(stream=source_bytes, filetype="pdf")
        try:
            return PdfDocument._compress_document(
                source,
                options,
                page_progress=page_progress,
                status_callback=status_callback,
                image_progress=image_progress,
            )
        finally:
            source.close()

    def build_reduced_document(
        self,
        options: ReduceSizeOptions,
        *,
        page_progress: Callable[[int, int], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> fitz.Document:
        if len(self._doc) == 0:
            raise ValueError("페이지가 없습니다.")
        return self._compress_document(
            self._doc,
            options,
            page_progress=page_progress,
            status_callback=status_callback,
            image_progress=image_progress,
        )

    def estimate_reduced_size(
        self,
        options: ReduceSizeOptions,
        *,
        page_progress: Callable[[int, int], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        reduced = self.build_reduced_document(
            options,
            page_progress=page_progress,
            status_callback=status_callback,
            image_progress=image_progress,
        )
        try:
            return self._measure_doc_bytes(reduced)
        finally:
            reduced.close()

    def apply_reduced_payload(self, payload: bytes) -> tuple[int, int]:
        """Replace the open document with a pre-built reduced PDF payload."""
        if len(self._doc) == 0:
            raise ValueError("페이지가 없습니다.")
        before = len(self.save_to_bytes())
        self._record_undo_checkpoint()
        self._doc.close()
        self._doc = fitz.open(stream=payload, filetype="pdf")
        after = len(payload)
        self._touch()
        return before, after

    def apply_reduce_size(
        self,
        options: ReduceSizeOptions,
        *,
        page_progress: Callable[[int, int], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[int, int]:
        if len(self._doc) == 0:
            raise ValueError("페이지가 없습니다.")
        if status_callback is not None:
            status_callback("용량 줄이기를 시작합니다...")
        before = len(self.save_to_bytes())
        self._record_undo_checkpoint()
        reduced = self.build_reduced_document(
            options,
            page_progress=page_progress,
            status_callback=status_callback,
            image_progress=image_progress,
        )
        try:
            if status_callback is not None:
                status_callback("문서를 저장하는 중...")
            after_bytes = PdfDocument._serialize_doc_bytes(reduced)
            self._doc.close()
            self._doc = fitz.open(stream=after_bytes, filetype="pdf")
            after = len(after_bytes)
        finally:
            reduced.close()
        self._touch()
        if status_callback is not None:
            status_callback(
                f"완료: {format_file_size(before)} → {format_file_size(after)}"
            )
        return before, after

    def render_page_crop_pixmap(
        self,
        doc: fitz.Document,
        page_index: int,
        zoom: float = 1.5,
        *,
        crop_fraction: float = 0.35,
    ) -> fitz.Pixmap:
        page = doc[page_index]
        clip = fitz.Rect(
            page.rect.x0,
            page.rect.y0,
            page.rect.x1,
            page.rect.y0 + page.rect.height * crop_fraction,
        )
        matrix = fitz.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=matrix, clip=clip, alpha=False, annots=True)

    def render_page_preview_crop(
        self,
        page_index: int,
        zoom: float = 1.5,
        *,
        crop_fraction: float = 0.35,
    ) -> fitz.Pixmap:
        return self.render_page_crop_pixmap(
            self._doc,
            page_index,
            zoom=zoom,
            crop_fraction=crop_fraction,
        )

    def mark_saved(self) -> None:
        self._modified = False

    def _touch(self) -> None:
        self._modified = True

    def get_page_rect(self, index: int) -> fitz.Rect:
        return self._doc[index].rect

    def get_text_in_rect(self, index: int, rect: fitz.Rect) -> str:
        if rect.is_empty or rect.is_infinite:
            return ""
        page = self._doc[index]
        return page.get_text("text", clip=rect).strip()

    def get_word_highlight_rects(
        self, index: int, rect: fitz.Rect, zoom: float
    ) -> list[tuple[float, float, float, float]]:
        if rect.is_empty or rect.is_infinite:
            return []
        page = self._doc[index]
        highlights: list[tuple[float, float, float, float]] = []
        for word in page.get_text("words", clip=rect):
            x0, y0, x1, y1 = word[:4]
            highlights.append((x0 * zoom, y0 * zoom, (x1 - x0) * zoom, (y1 - y0) * zoom))
        return highlights

    def search_text(self, query: str) -> list[SearchHit]:
        needle = query.strip()
        if not needle:
            return []
        hits: list[SearchHit] = []
        for page_index in range(len(self._doc)):
            page = self._doc[page_index]
            for rect in page.search_for(needle):
                hits.append(SearchHit(page_index, rect))
        return hits

    @staticmethod
    def _insert_pdf_pages(
        target: fitz.Document,
        source: fitz.Document,
        *,
        from_page: int,
        to_page: int,
        start_at: int,
    ) -> None:
        """Copy PDF pages without rasterizing so text/image page types are preserved."""
        target.insert_pdf(
            source,
            from_page=from_page,
            to_page=to_page,
            start_at=start_at,
            links=True,
            annots=True,
        )

    def get_page_size_cm(self, index: int) -> tuple[float, float]:
        rect = self.get_page_rect(index)
        width_cm = rect.width * 2.54 / 72
        height_cm = rect.height * 2.54 / 72
        return round(width_cm, 2), round(height_cm, 2)

    def render_page_pixmap(self, index: int, zoom: float = 1.0) -> fitz.Pixmap:
        if self.rendering_paused:
            raise RuntimeError("rendering paused")
        page = self._doc[index]
        matrix = fitz.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=matrix, alpha=False, annots=False)

    def render_thumbnail_pixmap(self, index: int, max_width: int = 120) -> fitz.Pixmap:
        if self.rendering_paused:
            raise RuntimeError("rendering paused")
        page = self._doc[index]
        scale = max_width / page.rect.width
        matrix = fitz.Matrix(scale, scale)
        return page.get_pixmap(matrix=matrix, alpha=False, annots=False)

    def delete_pages(self, indices: list[int], *, record_undo: bool = True) -> None:
        if not indices:
            return
        if record_undo:
            self._record_undo_checkpoint()
        for index in sorted(set(indices), reverse=True):
            if 0 <= index < len(self._doc):
                self._doc.delete_page(index)
        self._touch()

    def move_pages_to_index(self, indices: list[int], target_index: int) -> int | None:
        """Move *indices* (document order) to insert before *target_index*.

        Returns the new start index, or None if nothing changed.
        """
        indices = sorted({index for index in indices if 0 <= index < len(self._doc)})
        page_count = len(self._doc)
        if not indices or len(indices) >= page_count:
            return None

        target_index = max(0, min(target_index, page_count))
        insert_at = target_index
        for index in indices:
            if index < target_index:
                insert_at -= 1
        insert_at = max(0, min(insert_at, page_count - len(indices)))

        if (
            insert_at == indices[0]
            and indices == list(range(indices[0], indices[0] + len(indices)))
        ):
            return None

        self._record_undo_checkpoint()
        temp = fitz.open()
        try:
            for index in indices:
                self._insert_pdf_pages(
                    temp,
                    self._doc,
                    from_page=index,
                    to_page=index,
                    start_at=temp.page_count,
                )
            for index in reversed(indices):
                self._doc.delete_page(index)
            self._insert_pdf_pages(
                self._doc,
                temp,
                from_page=0,
                to_page=temp.page_count - 1,
                start_at=insert_at,
            )
        finally:
            temp.close()

        self._touch()
        return insert_at

    def rotate_pages(self, indices: list[int], degrees: int) -> None:
        if not indices:
            return
        self._record_undo_checkpoint()
        for index in indices:
            if 0 <= index < len(self._doc):
                page = self._doc[index]
                page.set_rotation((page.rotation + degrees) % 360)
        self._touch()

    def insert_files_at(self, index: int, file_paths: list[str]) -> int:
        """Insert PDF pages or images at *index*. Returns number of pages added."""
        index = max(0, min(index, len(self._doc)))
        if not file_paths:
            return 0
        added = 0
        for file_path in file_paths:
            ext = Path(file_path).suffix.lower()
            if ext not in PDF_EXTENSIONS and ext not in IMAGE_EXTENSIONS:
                continue
            if added == 0:
                self._record_undo_checkpoint()
            if ext in PDF_EXTENSIONS:
                added += self._insert_pdf_at(index + added, file_path)
            elif ext in IMAGE_EXTENSIONS:
                self._insert_image_at(index + added, file_path)
                added += 1
        if added:
            self._touch()
        return added

    def insert_blank_page_at(self, index: int) -> None:
        """Insert a blank page at *index* (same size as a nearby page, or A4 if empty)."""
        index = max(0, min(index, len(self._doc)))
        self._record_undo_checkpoint()
        if len(self._doc) == 0:
            self._doc.new_page(width=595, height=842)
        else:
            ref_index = min(index, len(self._doc) - 1)
            rect = self._doc[ref_index].rect
            self._doc.new_page(pno=index, width=rect.width, height=rect.height)
        self._touch()

    def _insert_pdf_at(self, index: int, pdf_path: str) -> int:
        src = fitz.open(pdf_path)
        try:
            page_count = len(src)
            if page_count:
                self._insert_pdf_pages(
                    self._doc,
                    src,
                    from_page=0,
                    to_page=page_count - 1,
                    start_at=index,
                )
            return page_count
        finally:
            src.close()

    def _insert_image_at(self, index: int, image_path: str) -> None:
        img_pdf = PdfDocument._open_image_as_document(image_path)
        try:
            self._insert_pdf_pages(
                self._doc,
                img_pdf,
                from_page=0,
                to_page=img_pdf.page_count - 1,
                start_at=index,
            )
        finally:
            img_pdf.close()

    def _open_pdf_for_page_indices(self, indices: list[int]) -> fitz.Document:
        ordered = sorted({index for index in indices if 0 <= index < len(self._doc)})
        if not ordered:
            raise ValueError("페이지를 선택하세요.")
        out = fitz.open()
        for index in ordered:
            self._insert_pdf_pages(
                out,
                self._doc,
                from_page=index,
                to_page=index,
                start_at=out.page_count,
            )
        return out

    def extract_pages_to_bytes(self, indices: list[int]) -> bytes:
        out = self._open_pdf_for_page_indices(indices)
        try:
            return self._serialize_doc_bytes(out)
        finally:
            out.close()

    def insert_pages_from_bytes(self, index: int, pdf_bytes: bytes) -> int:
        index = max(0, min(index, len(self._doc)))
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            page_count = len(src)
            if page_count == 0:
                return 0
            self._record_undo_checkpoint()
            self._insert_pdf_pages(
                self._doc,
                src,
                from_page=0,
                to_page=page_count - 1,
                start_at=index,
            )
            self._touch()
            return page_count
        finally:
            src.close()

    def export_pages_to_pdf(self, indices: list[int], path: str) -> None:
        out = self._open_pdf_for_page_indices(indices)
        try:
            out.save(path, **PDF_SAVE_KWARGS)
        finally:
            out.close()

    def export_pages_as_images(
        self,
        indices: list[int],
        folder: str,
        image_format: str = "png",
        dpi: int = 150,
    ) -> list[str]:
        if not indices:
            raise ValueError("보낼 페이지를 선택하세요.")
        folder_path = Path(folder)
        folder_path.mkdir(parents=True, exist_ok=True)
        ext = image_format.lower().lstrip(".")
        saved: list[str] = []
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        for index in sorted(indices):
            if 0 <= index < len(self._doc):
                page = self._doc[index]
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                filename = folder_path / f"page_{index + 1:04d}.{ext}"
                pix.save(str(filename))
                saved.append(str(filename))
        return saved

    @staticmethod
    def is_supported_file(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in PDF_EXTENSIONS or ext in IMAGE_EXTENSIONS
