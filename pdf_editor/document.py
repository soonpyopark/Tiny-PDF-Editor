"""PDF document model backed by PyMuPDF."""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import fitz

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
PDF_EXTENSIONS = {".pdf"}


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
    grayscale: bool = False
    monochrome: bool = False


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


class PdfDocument:
    """In-memory PDF with page insert, delete, rotate, and export operations."""

    def __init__(self) -> None:
        self._doc = fitz.open()
        self._source_path: str | None = None
        self._modified = False
        self._render_pause_depth = 0

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
        pdf_bytes = Path(path).read_bytes()
        new_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        del pdf_bytes
        self._doc.close()
        self._doc = new_doc
        self._source_path = path
        self._modified = False

    def new_document(self) -> None:
        self._doc.close()
        self._doc = fitz.open()
        self._source_path = None
        self._modified = False

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
        """Replace an image stream while keeping its PDF /Mask reference."""
        pdf_object = (
            f"<< /Type /XObject /Subtype /Image"
            f" /Width {width} /Height {height}"
            f" /ColorSpace /{colorspace} /BitsPerComponent 8"
            f" /Filter /DCTDecode"
            f" /Mask {mask_xref} 0 R"
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
        mask_map = PdfDocument._collect_image_smask_map(doc)
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
                    mask_xref = mask_map.get(xref, 0)
                    if mask_xref > 0:
                        PdfDocument._replace_image_jpeg_preserving_mask(
                            doc,
                            xref,
                            stream=stream,
                            width=converted.width,
                            height=converted.height,
                            mask_xref=mask_xref,
                        )
                    else:
                        page.replace_image(xref, stream=stream)
                except Exception:
                    continue
                finally:
                    converted = None
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
        mask_map = PdfDocument._collect_image_smask_map(doc)

        for xref, (display_rect, page_index, smask) in targets.items():
            if display_rect.is_empty:
                continue

            pix = PdfDocument._safe_pixmap_from_xref(doc, xref)
            if pix is None:
                continue

            scaled: fitz.Pixmap | None = None
            try:
                effective_dpi = PdfDocument._image_effective_dpi(pix, display_rect)
                if (
                    dpi_threshold is not None
                    and effective_dpi > 0
                    and effective_dpi < dpi_threshold
                ):
                    continue

                target_w = max(1, int(display_rect.width * target_dpi / 72))
                target_h = max(1, int(display_rect.height * target_dpi / 72))
                scaled = PdfDocument._downsample_pixmap(pix, target_w, target_h)
                stream = scaled.tobytes("jpeg", jpg_quality=quality)
                if smask > 0:
                    PdfDocument._replace_image_stream_preserving_mask(
                        doc,
                        xref,
                        stream=stream,
                        width=scaled.width,
                        height=scaled.height,
                        mask_xref=smask,
                        colorspace=PdfDocument._pixmap_colorspace_name(scaled),
                    )
                else:
                    doc[page_index].replace_image(xref, stream=stream)
            except Exception:
                continue
            finally:
                scaled = None
                pix = None

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

            if display_rect.is_empty:
                continue

            target_w = max(1, int(display_rect.width * target_dpi / 72))
            target_h = max(1, int(display_rect.height * target_dpi / 72))

            pix: fitz.Pixmap | None = None
            scaled: fitz.Pixmap | None = None
            pix = PdfDocument._safe_pixmap_from_xref(doc, xref)
            if pix is None:
                continue

            effective_dpi = PdfDocument._image_effective_dpi(pix, display_rect)
            scaled = PdfDocument._downsample_pixmap(pix, target_w, target_h)
            resized = scaled.width < pix.width or scaled.height < pix.height

            if smask > 0:
                pass
            elif pix.alpha and display_rect.width < 64 and display_rect.height < 64:
                continue
            elif not resized and effective_dpi <= target_dpi:
                continue

            try:
                if not resized:
                    scaled = pix
                stream = scaled.tobytes("jpeg", jpg_quality=quality)
                if smask > 0:
                    PdfDocument._replace_image_stream_preserving_mask(
                        doc,
                        xref,
                        stream=stream,
                        width=scaled.width,
                        height=scaled.height,
                        mask_xref=smask,
                        colorspace=PdfDocument._pixmap_colorspace_name(scaled),
                    )
                else:
                    doc[page_index].replace_image(xref, stream=stream)
            except Exception:
                continue
            finally:
                scaled = None
                pix = None

    @staticmethod
    def _scale_single_page_in_place(
        doc: fitz.Document,
        page_index: int,
        scale: float,
    ) -> None:
        """Scale one page's content and media box without rasterizing or duplicating."""
        if abs(scale - 1.0) < 1e-6:
            return
        page = doc[page_index]
        # Use mediabox (not page.rect) so rotated pages scale correctly.
        box = page.mediabox
        new_rect = fitz.Rect(
            0,
            0,
            max(1.0, round(box.width * scale, 4)),
            max(1.0, round(box.height * scale, 4)),
        )
        page.wrap_contents()
        xrefs = page.get_contents()
        if not xrefs:
            page.set_mediabox(new_rect)
            return
        if isinstance(xrefs, int):
            xrefs = [xrefs]
        prefix = f"q {scale} 0 0 {scale} 0 0 cm\n".encode()
        suffix = b"\nQ"
        for xref in xrefs:
            content = doc.xref_stream(xref)
            doc.update_stream(xref, prefix + content + suffix)
        page.set_mediabox(new_rect)

    @staticmethod
    def _scale_document_geometry(
        doc: fitz.Document,
        percent: int,
        *,
        page_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Scale each page in place by *percent* (aspect ratio kept, text preserved)."""
        if percent >= 100:
            return
        scale = percent / 100.0
        page_count = len(doc)
        for index in range(page_count):
            PdfDocument._scale_single_page_in_place(doc, index, scale)
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
        if status_callback is not None:
            status_callback(
                f"페이지 크기를 {options.image_size_percent}%로 조정하는 중..."
            )
        PdfDocument._scale_document_geometry(
            doc,
            options.image_size_percent,
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

    def delete_pages(self, indices: list[int]) -> None:
        if not indices:
            return
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
        for index in indices:
            if 0 <= index < len(self._doc):
                page = self._doc[index]
                page.set_rotation((page.rotation + degrees) % 360)
        self._touch()

    def insert_files_at(self, index: int, file_paths: list[str]) -> int:
        """Insert PDF pages or images at *index*. Returns number of pages added."""
        index = max(0, min(index, len(self._doc)))
        added = 0
        for file_path in file_paths:
            ext = Path(file_path).suffix.lower()
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
        img_doc = fitz.open(image_path)
        try:
            pdf_bytes = img_doc.convert_to_pdf()
        finally:
            img_doc.close()
        img_pdf = fitz.open("pdf", pdf_bytes)
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

    def export_pages_to_pdf(self, indices: list[int], path: str) -> None:
        if not indices:
            raise ValueError("보낼 페이지를 선택하세요.")
        out = fitz.open()
        try:
            for index in sorted(indices):
                if 0 <= index < len(self._doc):
                    self._insert_pdf_pages(
                        out,
                        self._doc,
                        from_page=index,
                        to_page=index,
                        start_at=out.page_count,
                    )
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
