"""PDF document model backed by PyMuPDF."""

from __future__ import annotations

import hashlib
import io
import os
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
    """Internal image recompress settings used by optimize."""

    jpeg_quality: int = 50
    max_dpi: int = 150
    image_size_percent: int = 100


OPTIMIZE_DPI_CHOICES = (36, 48, 72, 96, 120, 150, 200, 300, 400, 600)
OPTIMIZE_DEFAULT_JPEG_QUALITY = 25
# Distiller PDFs use tiny FlateDecode tiles; JPEG is ~30x larger — preserve them.
OPTIMIZE_PRESERVE_FLATE_MAX_BYTES = 4096


@dataclass(frozen=True)
class OptimizeSizeOptions:
    """Acrobat-style optimize settings (data-only image recompress + cleanup)."""

    image_dpi: int = 72
    image_quality_percent: int = 100
    image_size_percent: int = 100
    remove_duplicate_resources: bool = True
    compress_streams: bool = True
    compress_fonts: bool = True


_MICRO_IMAGE_MAX_PT = 12.0
_MAX_UNDO_LEVELS = 50
_EMPTY_SNAPSHOT = b""


MIN_IMAGE_DPI = 24

PDF_SAVE_KWARGS: dict[str, object] = {
    "garbage": 4,
    "deflate": True,
    "use_objstms": True,
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
        self._undo_stack.append(self._snapshot_bytes())
        if len(self._undo_stack) > _MAX_UNDO_LEVELS:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore_from_snapshot(self, payload: bytes) -> None:
        self._restoring_history = True
        try:
            self._doc.close()
            if not payload:
                self._doc = fitz.open()
            else:
                self._doc = fitz.open(stream=payload, filetype="pdf")
            self._touch()
        finally:
            self._restoring_history = False

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot_bytes())
        payload = self._undo_stack.pop()
        self._restore_from_snapshot(payload)
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot_bytes())
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
        if len(self._doc) == 0:
            return _EMPTY_SNAPSHOT
        buffer = io.BytesIO()
        self._doc.save(buffer, **PDF_SAVE_KWARGS)
        return buffer.getvalue()

    def _snapshot_bytes(self) -> bytes:
        """Serialize document for undo/redo; empty documents use a sentinel payload."""
        return self.save_to_bytes()

    @staticmethod
    def _serialize_doc_bytes(doc: fitz.Document) -> bytes:
        buffer = io.BytesIO()
        doc.save(buffer, **PDF_SAVE_KWARGS)
        return buffer.getvalue()

    def current_file_size(self) -> int:
        if len(self._doc) == 0:
            return 0
        payload = self.save_to_bytes()
        return 0 if not payload else len(payload)

    def _clone_document(self) -> fitz.Document:
        payload = self.save_to_bytes()
        if not payload:
            return fitz.open()
        return fitz.open(stream=payload, filetype="pdf")

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
    def _is_micro_image_rect(display_rect: fitz.Rect) -> bool:
        if display_rect.is_empty:
            return True
        return max(display_rect.width, display_rect.height) < _MICRO_IMAGE_MAX_PT

    @staticmethod
    def _pixmap_for_jpeg_export(pix: fitz.Pixmap) -> fitz.Pixmap:
        """Prepare a pixmap for JPEG export (CMYK/alpha JPEG often renders as black)."""
        if pix.colorspace is None:
            return pix
        if pix.alpha or pix.colorspace.n not in (1, 3):
            return fitz.Pixmap(fitz.csRGB, pix)
        return pix

    @staticmethod
    def _jpeg_smaller_than(
        pix: fitz.Pixmap,
        old_size: int,
        jpeg_quality: int,
    ) -> bytes | None:
        """Return JPEG bytes smaller than old_size, trying lower qualities if needed."""
        if old_size <= 0:
            return pix.tobytes("jpeg", jpg_quality=jpeg_quality)
        qualities: list[int] = []
        for q in range(max(5, jpeg_quality), 4, -5):
            if q not in qualities:
                qualities.append(q)
        if 5 not in qualities:
            qualities.append(5)
        for q in qualities:
            stream = pix.tobytes("jpeg", jpg_quality=q)
            if len(stream) < old_size:
                return stream
        return None

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
        include_micro: bool = False,
        preserve_small_flate_max_bytes: int | None = None,
        require_smaller_stream: bool = False,
        smask_xref: int = 0,
        image_size_percent: int = 100,
    ) -> bool:
        """Downsample one embedded image to its on-page display size; return True if updated."""
        if display_rect.is_empty:
            return False
        if not include_micro and PdfDocument._is_micro_image_rect(display_rect):
            return False

        old_stream = doc.xref_stream_raw(xref) or b""
        old_size = len(old_stream)
        if preserve_small_flate_max_bytes is not None and old_size > 0:
            _, flt = doc.xref_get_key(xref, "Filter")
            if (
                "FlateDecode" in str(flt)
                and old_size <= preserve_small_flate_max_bytes
            ):
                return False

        target_w = max(1, int(display_rect.width * target_dpi / 72))
        target_h = max(1, int(display_rect.height * target_dpi / 72))
        size_scale = max(1, min(100, image_size_percent)) / 100.0
        if size_scale < 1.0:
            target_w = max(1, int(target_w * size_scale))
            target_h = max(1, int(target_h * size_scale))
        effective_target_dpi = target_dpi * size_scale

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
                and effective_dpi <= effective_target_dpi
            ):
                return False
            jpeg_pix = PdfDocument._pixmap_for_jpeg_export(scaled)
            if require_smaller_stream:
                stream = PdfDocument._jpeg_smaller_than(
                    jpeg_pix,
                    old_size,
                    jpeg_quality,
                )
                if stream is None:
                    return False
            else:
                stream = jpeg_pix.tobytes("jpeg", jpg_quality=jpeg_quality)
            if smask_xref > 0:
                PdfDocument._replace_image_stream_preserving_mask(
                    doc,
                    xref,
                    stream=stream,
                    width=jpeg_pix.width,
                    height=jpeg_pix.height,
                    mask_xref=smask_xref,
                    colorspace=PdfDocument._pixmap_colorspace_name(jpeg_pix),
                )
            else:
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
        image_progress: Callable[[int, int], None] | None = None,
        preserve_small_flate_max_bytes: int | None = None,
        require_smaller_stream: bool = False,
        skip_if_display_dpi_met: bool = False,
    ) -> None:
        """Recompress each embedded image; skip images that cannot be decoded."""
        quality = max(1, min(100, options.jpeg_quality))
        targets = PdfDocument._collect_image_resize_targets(doc)
        total = len(targets)
        progress_stride = max(1, total // 50) if total else 1

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
                min_effective_dpi=float(dpi_threshold)
                if dpi_threshold is not None
                else None,
                skip_if_display_dpi_met=skip_if_display_dpi_met,
                include_micro=True,
                preserve_small_flate_max_bytes=preserve_small_flate_max_bytes,
                require_smaller_stream=require_smaller_stream,
                smask_xref=smask,
                image_size_percent=options.image_size_percent,
            )

    @staticmethod
    def _rewrite_images_preserve_text(
        doc: fitz.Document,
        options: ReduceSizeOptions,
        *,
        target_dpi: int,
        dpi_threshold: int | None,
        image_progress: Callable[[int, int], None] | None = None,
        preserve_small_flate_max_bytes: int | None = None,
        require_smaller_stream: bool = False,
        skip_if_display_dpi_met: bool = False,
    ) -> None:
        """Recompress embedded images only; do not recolor or outline text."""
        PdfDocument._recompress_images_individually(
            doc,
            options,
            target_dpi=target_dpi,
            dpi_threshold=dpi_threshold,
            image_progress=image_progress,
            preserve_small_flate_max_bytes=preserve_small_flate_max_bytes,
            require_smaller_stream=require_smaller_stream,
            skip_if_display_dpi_met=skip_if_display_dpi_met,
        )

    _DEDUP_DICT_KEYS = (
        "Width",
        "Height",
        "ColorSpace",
        "BitsPerComponent",
        "Filter",
        "Decode",
        "DecodeParms",
        "Intent",
        "OC",
        "Interpolate",
    )

    @staticmethod
    def _embedded_image_fingerprint(
        doc: fitz.Document,
        xref: int,
        *,
        smask_xref: int = 0,
    ) -> bytes | None:
        """Return a stable fingerprint for identical embedded image objects."""
        if not doc.xref_is_image(xref):
            return None

        hasher = hashlib.sha256()
        hasher.update(doc.xref_stream_raw(xref) or b"")
        for key in PdfDocument._DEDUP_DICT_KEYS:
            kind, value = doc.xref_get_key(xref, key)
            if kind != "null":
                hasher.update(key.encode("ascii"))
                hasher.update(value.encode("ascii", errors="replace"))

        if smask_xref <= 0:
            for mask_key in ("SMask", "Mask"):
                kind, value = doc.xref_get_key(xref, mask_key)
                if kind == "xref":
                    smask_xref = int(value.split()[0])
                    break
                if kind != "null" and mask_key == "Mask":
                    hasher.update(b"Mask:")
                    hasher.update(value.encode("ascii", errors="replace"))
                    smask_xref = 0
                    break

        if smask_xref > 0 and doc.xref_is_image(smask_xref):
            smask_fp = PdfDocument._embedded_image_fingerprint(doc, smask_xref)
            if smask_fp is not None:
                hasher.update(b"|SMask|")
                hasher.update(smask_fp)
        return hasher.digest()

    @staticmethod
    def _collect_image_resource_refs(
        doc: fitz.Document,
    ) -> list[tuple[int, str, int]]:
        """Return (container_xref, resource_name, image_xref) triples."""
        refs: list[tuple[int, str, int]] = []
        for page_index in range(len(doc)):
            try:
                images = doc.get_page_images(page_index, full=True)
                page_xref = doc.page_xref(page_index)
            except Exception:
                continue
            for img in images:
                xref = int(img[0])
                name = str(img[7]) if len(img) > 7 else ""
                referencer = int(img[9]) if len(img) > 9 else 0
                container = referencer if referencer else page_xref
                if name and xref:
                    refs.append((container, name, xref))
        return refs

    @staticmethod
    def _build_image_dedup_redirect(
        doc: fitz.Document,
        *,
        smask_by_xref: dict[int, int] | None = None,
    ) -> dict[int, int]:
        """Map duplicate image xrefs to a canonical xref with identical content."""
        fingerprint_to_canonical: dict[bytes, int] = {}
        redirect: dict[int, int] = {}
        seen_xrefs: set[int] = set()

        for page_index in range(len(doc)):
            try:
                images = doc.get_page_images(page_index, full=True)
            except Exception:
                continue
            for img in images:
                seen_xrefs.add(int(img[0]))
                if len(img) > 1 and img[1]:
                    seen_xrefs.add(int(img[1]))

        for xref in range(1, doc.xref_length()):
            try:
                if doc.xref_is_image(xref):
                    seen_xrefs.add(xref)
            except Exception:
                continue

        for xref in sorted(seen_xrefs):
            if xref in redirect:
                continue
            smask = smask_by_xref.get(xref, 0) if smask_by_xref else 0
            fingerprint = PdfDocument._embedded_image_fingerprint(
                doc,
                xref,
                smask_xref=smask,
            )
            if fingerprint is None:
                continue
            canonical = fingerprint_to_canonical.get(fingerprint)
            if canonical is None:
                fingerprint_to_canonical[fingerprint] = xref
            elif canonical != xref:
                redirect[xref] = canonical
        return redirect

    @staticmethod
    def _apply_image_dedup_redirect(
        doc: fitz.Document,
        redirect: dict[int, int],
    ) -> int:
        """Retarget duplicate image xrefs; orphaned objects are dropped on compact."""
        if not redirect:
            return 0

        resolved: dict[int, int] = {}
        for duplicate in redirect:
            target = duplicate
            while target in redirect:
                target = redirect[target]
            resolved[duplicate] = target

        for container, name, xref in PdfDocument._collect_image_resource_refs(doc):
            target = resolved.get(xref)
            if target is None:
                continue
            try:
                if not doc.xref_is_image(target):
                    continue
            except Exception:
                continue
            try:
                doc.xref_set_key(
                    container,
                    f"Resources/XObject/{name}",
                    f"{target} 0 R",
                )
            except Exception:
                continue

        for xref in range(1, doc.xref_length()):
            try:
                if not doc.xref_is_image(xref):
                    continue
            except Exception:
                continue
            for key in ("SMask", "Mask"):
                kind, value = doc.xref_get_key(xref, key)
                if kind != "xref":
                    continue
                ref_xref = int(value.split()[0])
                target = resolved.get(ref_xref)
                if target is None:
                    continue
                try:
                    doc.xref_set_key(xref, key, f"{target} 0 R")
                except Exception:
                    continue
        return len(resolved)

    @staticmethod
    def _deduplicate_embedded_images(doc: fitz.Document) -> int:
        """Merge identical embedded image xrefs without changing layout."""
        smask_map = PdfDocument._collect_image_smask_map(doc)
        redirect = PdfDocument._build_image_dedup_redirect(doc, smask_by_xref=smask_map)
        return PdfDocument._apply_image_dedup_redirect(doc, redirect)

    @staticmethod
    def _optimize_jpeg_quality(quality_percent: int) -> int:
        """Map UI quality % (100 = default optimize baseline) to JPEG quality."""
        pct = max(1, min(100, quality_percent))
        return max(
            5,
            min(95, round(OPTIMIZE_DEFAULT_JPEG_QUALITY * pct / 100)),
        )

    @staticmethod
    def _optimize_save_kwargs(options: OptimizeSizeOptions) -> dict[str, object]:
        if options.compress_streams:
            return dict(PDF_SAVE_KWARGS)
        return {"garbage": 4, "deflate": False, "use_objstms": False}

    @staticmethod
    def build_optimized_payload(
        source_bytes: bytes,
        options: OptimizeSizeOptions,
        *,
        status_callback: Callable[[str], None] | None = None,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> bytes:
        """Acrobat-style optimize: recompress images at DPI, dedup, optional cleanup."""
        source = fitz.open(stream=source_bytes, filetype="pdf")
        try:
            return PdfDocument._optimize_document(
                source,
                options,
                status_callback=status_callback,
                image_progress=image_progress,
            )
        finally:
            source.close()

    @staticmethod
    def _optimize_document(
        source: fitz.Document,
        options: OptimizeSizeOptions,
        *,
        status_callback: Callable[[str], None] | None = None,
        image_progress: Callable[[int, int], None] | None = None,
    ) -> bytes:
        working = fitz.open(stream=source.tobytes(), filetype="pdf")
        dedup_merged = 0
        try:
            if status_callback is not None:
                status_callback(
                    f"이미지를 {options.image_dpi}dpi로 재압축하는 중... "
                    "(레이아웃·검색 유지)"
                )
            reduce_opts = ReduceSizeOptions(
                max_dpi=max(MIN_IMAGE_DPI, options.image_dpi),
                jpeg_quality=PdfDocument._optimize_jpeg_quality(
                    options.image_quality_percent
                ),
                image_size_percent=max(1, min(100, options.image_size_percent)),
            )
            target_dpi = max(MIN_IMAGE_DPI, options.image_dpi)
            dpi_threshold = target_dpi + 1
            try:
                PdfDocument._rewrite_images_preserve_text(
                    working,
                    reduce_opts,
                    target_dpi=target_dpi,
                    dpi_threshold=dpi_threshold,
                    image_progress=image_progress,
                    preserve_small_flate_max_bytes=OPTIMIZE_PRESERVE_FLATE_MAX_BYTES,
                    require_smaller_stream=True,
                    skip_if_display_dpi_met=True,
                )
            except Exception:
                if status_callback is not None:
                    status_callback("일부 이미지 재압축을 건너뛰고 계속합니다...")

            if options.remove_duplicate_resources:
                if status_callback is not None:
                    status_callback("중복 리소스 제거 중...")
                dedup_merged = PdfDocument._deduplicate_embedded_images(working)
                if status_callback is not None and dedup_merged > 0:
                    status_callback(f"중복 리소스 {dedup_merged}개 병합됨")

            if options.compress_fonts:
                if status_callback is not None:
                    status_callback("내장 글꼴 압축 중...")
                try:
                    working.subset_fonts()
                except Exception:
                    pass

            if status_callback is not None:
                status_callback("문서를 저장하는 중...")
            return working.tobytes(**PdfDocument._optimize_save_kwargs(options))
        finally:
            working.close()

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

    def apply_reduced_payload(self, payload: bytes) -> tuple[int, int]:
        """Replace the open document with a pre-built optimized PDF payload."""
        if len(self._doc) == 0:
            raise ValueError("페이지가 없습니다.")
        before = len(self.save_to_bytes())
        self._record_undo_checkpoint()
        self._doc.close()
        self._doc = fitz.open(stream=payload, filetype="pdf")
        after = len(payload)
        self._touch()
        return before, after

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

    @staticmethod
    def _sanitize_export_basename(name: str) -> str:
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, "_")
        cleaned = name.strip(" .")
        return cleaned or "document"

    def export_pages_as_images(
        self,
        indices: list[int],
        folder: str,
        *,
        base_name: str | None = None,
    ) -> list[str]:
        if not indices:
            raise ValueError("보낼 페이지를 선택하세요.")
        folder_path = Path(folder)
        folder_path.mkdir(parents=True, exist_ok=True)
        stem = self._sanitize_export_basename(
            base_name if base_name is not None else Path(self.display_name).stem
        )
        saved: list[str] = []
        matrix = fitz.Identity
        for index in sorted(indices):
            if 0 <= index < len(self._doc):
                page = self._doc[index]
                pix = page.get_pixmap(matrix=matrix, alpha=False, annots=True)
                filename = folder_path / f"{stem}_{index + 1}.png"
                pix.save(str(filename))
                saved.append(str(filename))
        return saved

    @staticmethod
    def is_supported_file(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in PDF_EXTENSIONS or ext in IMAGE_EXTENSIONS
