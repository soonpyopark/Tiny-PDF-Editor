"""PDF document model backed by PyMuPDF."""

from __future__ import annotations

import hashlib
import io
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import fitz

from pdf_editor.cross_page_selection import PageSelectionSegment

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_FILE_FILTER = (
    "지원 파일 (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp);;"
    "PDF (*.pdf);;"
    "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp);;"
    "모든 파일 (*.*)"
)


@dataclass(frozen=True)
class PdfPasswordOptions:
    user_password: str
    owner_password: str | None = None


@dataclass(frozen=True)
class SearchHit:
    page_index: int
    rect: fitz.Rect


@dataclass(frozen=True)
class TextMarkupEntry:
    """One highlight or underline annotation with extracted text."""

    page_index: int
    text: str
    kind: str  # "highlight" | "underline"
    rgb: tuple[float, float, float]
    sort_y: float = 0.0
    sort_x: float = 0.0
    page_rect: fitz.Rect | None = None
    group_id: str | None = None

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
_MARKUP_GROUP_TITLE_PREFIX = "tpe:g="


MIN_IMAGE_DPI = 24

PDF_SAVE_KWARGS: dict[str, object] = {
    "garbage": 4,
    "deflate": True,
    "use_objstms": True,
}


class PdfPasswordRequired(ValueError):
    """PDF needs a password before it can be read."""


class PdfPasswordRejected(PdfPasswordRequired):
    """Provided PDF password was incorrect."""


def configure_mupdf_messages() -> None:
    """Hide raw MuPDF stderr messages; callers handle failures in the UI."""
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)


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
        self._password_options: PdfPasswordOptions | None = None
        self._source_had_encryption = False

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

    @staticmethod
    def _metadata_shows_encryption(doc: fitz.Document) -> bool:
        try:
            metadata = doc.metadata
        except (ValueError, AttributeError):
            return False
        if not metadata:
            return False
        encryption = metadata.get("encryption")
        return bool(encryption and str(encryption) not in ("None", ""))

    @staticmethod
    def _doc_reports_encryption(doc: fitz.Document) -> bool:
        if doc.needs_pass:
            return True
        if getattr(doc, "is_encrypted", False):
            return True
        return PdfDocument._metadata_shows_encryption(doc)

    @staticmethod
    def _pdf_bytes_encrypted(pdf_bytes: bytes) -> bool:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return PdfDocument._doc_reports_encryption(doc)
        finally:
            doc.close()

    @staticmethod
    def _open_pdf_bytes(pdf_bytes: bytes, password: str | None = None) -> fitz.Document:
        fitz.TOOLS.mupdf_warnings(reset=True)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.needs_pass:
            if password is None:
                doc.close()
                raise PdfPasswordRequired("비밀번호가 필요합니다.")
            if not doc.authenticate(password):
                doc.close()
                raise PdfPasswordRejected("비밀번호가 올바르지 않습니다.")
        if doc.is_pdf:
            try:
                doc.repair()
            except Exception:
                pass
            if doc.is_repaired:
                try:
                    repaired = fitz.open(
                        stream=PdfDocument._raw_doc_bytes(doc),
                        filetype="pdf",
                    )
                    doc.close()
                    return repaired
                except Exception:
                    pass
        return doc

    @staticmethod
    def _open_pdf_path(path: str, password: str | None = None) -> fitz.Document:
        return PdfDocument._open_pdf_bytes(Path(path).read_bytes(), password=password)

    @staticmethod
    def _blank_page_pixmap(width: float, height: float, zoom: float) -> fitz.Pixmap:
        tmp = fitz.open()
        try:
            page = tmp.new_page(width=width, height=height)
            shape = page.new_shape()
            shape.draw_rect(page.rect)
            shape.finish(color=(0.93, 0.93, 0.93), fill=(0.93, 0.93, 0.93))
            shape.commit()
            return page.get_pixmap(
                matrix=fitz.Matrix(zoom, zoom),
                alpha=False,
                annots=False,
            )
        finally:
            tmp.close()

    def open_file(self, path: str, *, password: str | None = None) -> None:
        path = str(Path(path))
        ext = Path(path).suffix.lower()
        if ext in PDF_EXTENSIONS:
            pdf_bytes = Path(path).read_bytes()
            had_encryption = PdfDocument._pdf_bytes_encrypted(pdf_bytes)
            new_doc = PdfDocument._open_pdf_bytes(pdf_bytes, password=password)
            if password is not None:
                had_encryption = True
            if PdfDocument._metadata_shows_encryption(new_doc):
                had_encryption = True
            self._source_path = str(Path(path).resolve())
            self._source_had_encryption = had_encryption
            self._password_options = (
                PdfPasswordOptions(user_password=password)
                if password is not None
                else None
            )
        elif ext in IMAGE_EXTENSIONS:
            new_doc = PdfDocument._open_image_as_document(path)
            self._source_path = None
            self._source_had_encryption = False
            self._password_options = None
        else:
            raise ValueError(f"지원하지 않는 파일 형식입니다: {ext}")
        self._doc.close()
        self._doc = new_doc
        self._modified = False
        self.clear_history()

    def has_password_protection(self) -> bool:
        return self._password_options is not None or self._source_had_encryption

    def set_password_protection(
        self,
        user_password: str,
        owner_password: str | None = None,
    ) -> None:
        if not user_password:
            raise ValueError("비밀번호를 입력하세요.")
        if len(user_password) > 40:
            raise ValueError("비밀번호는 40자 이하여야 합니다.")
        if owner_password and len(owner_password) > 40:
            raise ValueError("소유자 비밀번호는 40자 이하여야 합니다.")
        self._password_options = PdfPasswordOptions(
            user_password=user_password,
            owner_password=owner_password,
        )
        self._source_had_encryption = True
        self._touch()

    def clear_password_protection(self) -> None:
        self._password_options = None
        self._source_had_encryption = False
        self._touch()

    def _save_kwargs(self) -> dict[str, object]:
        kwargs = dict(PDF_SAVE_KWARGS)
        if self._password_options is None:
            kwargs["encryption"] = fitz.mupdf.PDF_ENCRYPT_NONE
            return kwargs
        kwargs["encryption"] = fitz.mupdf.PDF_ENCRYPT_AES_256
        kwargs["user_pw"] = self._password_options.user_password
        owner = self._password_options.owner_password
        kwargs["owner_pw"] = owner if owner else self._password_options.user_password
        return kwargs

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
        self._password_options = None
        self._source_had_encryption = False
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
                self._doc = PdfDocument._open_pdf_bytes(payload)
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
                self._doc.save(str(staging), **self._save_kwargs())
                os.replace(str(staging), target)
            except Exception:
                staging.unlink(missing_ok=True)
                raise
        else:
            self._doc.save(target, **self._save_kwargs())

        self._source_path = target
        self._modified = False
        return target

    def save_to_bytes(self) -> bytes:
        if len(self._doc) == 0:
            return _EMPTY_SNAPSHOT
        buffer = io.BytesIO()
        self._doc.save(buffer, **self._save_kwargs())
        return buffer.getvalue()

    def _snapshot_bytes(self) -> bytes:
        """Serialize document for undo/redo; empty documents use a sentinel payload."""
        return self.save_to_bytes()

    @staticmethod
    def _raw_doc_bytes(doc: fitz.Document) -> bytes:
        buffer = io.BytesIO()
        doc.save(buffer, **PDF_SAVE_KWARGS, encryption=fitz.mupdf.PDF_ENCRYPT_NONE)
        return buffer.getvalue()

    def _serialize_doc_bytes(self, doc: fitz.Document | None = None) -> bytes:
        target = doc if doc is not None else self._doc
        buffer = io.BytesIO()
        target.save(buffer, **self._save_kwargs())
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
        return PdfDocument._open_pdf_bytes(payload)

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
    def _embedded_image_effective_dpi(
        width: int,
        height: int,
        display_rect: fitz.Rect,
    ) -> float:
        if width <= 0 or height <= 0 or display_rect.width <= 0 or display_rect.height <= 0:
            return 0.0
        return min(
            width / display_rect.width * 72,
            height / display_rect.height * 72,
        )

    def get_page_creation_dpi(self, index: int) -> int | None:
        """Area-weighted effective DPI of raster images embedded on one page."""
        page = self._doc[index]
        try:
            images = page.get_images(full=True)
        except Exception:
            return None

        weighted_dpi = 0.0
        total_area = 0.0
        for img in images:
            xref = int(img[0])
            width = int(img[2]) if len(img) > 2 else 0
            height = int(img[3]) if len(img) > 3 else 0
            if width <= 0 or height <= 0:
                continue
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue
            for rect in rects:
                if self._is_micro_image_rect(rect):
                    continue
                dpi = self._embedded_image_effective_dpi(width, height, rect)
                if dpi <= 0:
                    continue
                area = rect.width * rect.height
                weighted_dpi += dpi * area
                total_area += area

        if total_area <= 0:
            return None
        return int(round(weighted_dpi / total_area))

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

    @staticmethod
    def _word_line_id(word) -> tuple[int, int]:
        return int(word[5]), int(word[6])

    @staticmethod
    def _word_sort_key(word) -> tuple[int, int, int]:
        return int(word[5]), int(word[6]), int(word[7])

    @staticmethod
    def _word_index_at_point(words: list, point: fitz.Point) -> int:
        containing = [
            index
            for index, word in enumerate(words)
            if fitz.Rect(word[:4]).contains(point)
        ]
        if containing:
            return containing[0]
        best_index = 0
        best_distance = float("inf")
        for index, word in enumerate(words):
            rect = fitz.Rect(word[:4])
            center_x = (rect.x0 + rect.x1) / 2
            center_y = (rect.y0 + rect.y1) / 2
            distance = (center_x - point.x) ** 2 + (center_y - point.y) ** 2
            if distance < best_distance:
                best_distance = distance
                best_index = index
        return best_index

    @staticmethod
    def _selection_text_from_words(words: list) -> str:
        if not words:
            return ""
        lines: list[str] = []
        current_line: tuple[int, int] | None = None
        parts: list[str] = []
        for word in words:
            line_id = PdfDocument._word_line_id(word)
            if line_id != current_line:
                if parts:
                    lines.append(" ".join(parts))
                parts = [str(word[4])]
                current_line = line_id
            else:
                parts.append(str(word[4]))
        if parts:
            lines.append(" ".join(parts))

        result: list[str] = []
        for line_text in lines:
            if result and result[-1].rstrip().endswith("."):
                result.append(" ")
            result.append(line_text)
        return "".join(result)

    @staticmethod
    def _plain_text_to_markup_text(text: str) -> str:
        """Apply markup line-join rules to plain extracted text."""
        if not text:
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return text.strip()
        result: list[str] = []
        for line_text in lines:
            if result and result[-1].rstrip().endswith("."):
                result.append(" ")
            result.append(line_text)
        return "".join(result)

    @staticmethod
    def _words_from_highlight_quads(page, quad_rects: list[fitz.Rect]) -> list:
        if not quad_rects:
            return []
        matched: list = []
        seen: set[tuple[int, int, int]] = set()
        for word in page.get_text("words"):
            word_rect = fitz.Rect(word[:4])
            word_key = PdfDocument._word_sort_key(word)
            if word_key in seen:
                continue
            for quad_rect in quad_rects:
                if word_rect.intersects(quad_rect):
                    seen.add(word_key)
                    matched.append(word)
                    break
        return sorted(matched, key=PdfDocument._word_sort_key)

    @staticmethod
    def _join_continued_text_parts(parts: list[str]) -> str:
        """Join cross-page segments with spaces instead of line breaks."""
        return " ".join(part.strip() for part in parts if part.strip())

    @staticmethod
    def _words_in_reading_order(page, page_rect: fitz.Rect) -> list:
        words = page.get_text("words", clip=page_rect)
        if not words:
            return []
        return sorted(words, key=PdfDocument._word_sort_key)

    @staticmethod
    def _rect_center(rect: fitz.Rect) -> fitz.Point:
        return fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)

    @staticmethod
    def _word_center_in_rect(word, page_rect: fitz.Rect) -> bool:
        return page_rect.contains(PdfDocument._rect_center(fitz.Rect(word[:4])))

    @staticmethod
    def _words_for_markup_in_rect(
        page,
        page_rect: fitz.Rect,
        selected_words: list | tuple | None = None,
    ) -> list:
        if selected_words:
            return sorted(selected_words, key=PdfDocument._word_sort_key)
        words = page.get_text("words")
        matched = [
            word
            for word in words
            if PdfDocument._word_center_in_rect(word, page_rect)
        ]
        if not matched:
            matched = [
                word
                for word in words
                if page_rect.contains(fitz.Rect(word[:4]))
            ]
        return sorted(matched, key=PdfDocument._word_sort_key)

    @staticmethod
    def _quad_from_rect(rect: fitz.Rect) -> fitz.Quad:
        return fitz.Quad(
            fitz.Point(rect.x0, rect.y1),
            fitz.Point(rect.x1, rect.y1),
            fitz.Point(rect.x0, rect.y0),
            fitz.Point(rect.x1, rect.y0),
        )

    @staticmethod
    def _markup_quads_from_words(words: list) -> list[fitz.Quad]:
        """Build highlight/underline quads including whitespace gaps on each line."""
        if not words:
            return []
        ordered = sorted(words, key=PdfDocument._word_sort_key)
        quads: list[fitz.Quad] = []
        line_words: list = [ordered[0]]
        current_line = PdfDocument._word_line_id(ordered[0])

        def flush_line(words_on_line: list) -> None:
            for index, word in enumerate(words_on_line):
                x0, y0, x1, y1 = word[:4]
                quads.append(PdfDocument._quad_from_rect(fitz.Rect(x0, y0, x1, y1)))
                if index + 1 >= len(words_on_line):
                    continue
                next_word = words_on_line[index + 1]
                nx0, ny0, nx1, ny1 = next_word[:4]
                gap_x0 = x1
                gap_x1 = nx0
                if gap_x1 <= gap_x0 + 0.1:
                    continue
                gy0 = min(y0, ny0)
                gy1 = max(y1, ny1)
                quads.append(
                    PdfDocument._quad_from_rect(fitz.Rect(gap_x0, gy0, gap_x1, gy1))
                )

        for word in ordered[1:]:
            if PdfDocument._word_line_id(word) != current_line:
                flush_line(line_words)
                line_words = [word]
                current_line = PdfDocument._word_line_id(word)
            else:
                line_words.append(word)
        flush_line(line_words)
        return quads

    @staticmethod
    def _markup_highlight_rects_from_words(
        words: list,
        zoom: float,
    ) -> list[tuple[float, float, float, float]]:
        rects: list[tuple[float, float, float, float]] = []
        for quad in PdfDocument._markup_quads_from_words(words):
            rect = quad.rect
            rects.append(
                (
                    rect.x0 * zoom,
                    rect.y0 * zoom,
                    (rect.x1 - rect.x0) * zoom,
                    (rect.y1 - rect.y0) * zoom,
                )
            )
        return rects

    @staticmethod
    def _word_quads_from_words(words: list) -> list[fitz.Quad]:
        return PdfDocument._markup_quads_from_words(words)

    def get_text_block_selection(
        self,
        page_index: int,
        anchor: fitz.Point,
        cursor: fitz.Point,
        zoom: float,
    ) -> tuple[fitz.Rect | None, list[tuple[float, float, float, float]], str, list]:
        """Select words line-wise: dragging down/up includes full intermediate lines."""
        if not (0 <= page_index < len(self._doc)):
            return None, [], "", []
        page = self._doc[page_index]
        words = page.get_text("words")
        if not words:
            return None, [], "", []

        anchor_idx = self._word_index_at_point(words, anchor)
        cursor_idx = self._word_index_at_point(words, cursor)
        anchor_word = words[anchor_idx]
        cursor_word = words[cursor_idx]

        line_id = self._word_line_id
        word_key = self._word_sort_key
        anchor_line = line_id(anchor_word)
        cursor_line = line_id(cursor_word)
        selected: list = []

        if anchor_line == cursor_line:
            lo_key, hi_key = sorted((word_key(anchor_word), word_key(cursor_word)))
            for word in words:
                if line_id(word) != anchor_line:
                    continue
                current_key = word_key(word)
                if lo_key <= current_key <= hi_key:
                    selected.append(word)
        elif anchor_line < cursor_line:
            anchor_key = word_key(anchor_word)
            cursor_key = word_key(cursor_word)
            for word in words:
                current_line = line_id(word)
                current_key = word_key(word)
                if current_line == anchor_line:
                    if current_key >= anchor_key:
                        selected.append(word)
                elif current_line == cursor_line:
                    if current_key <= cursor_key:
                        selected.append(word)
                elif anchor_line < current_line < cursor_line:
                    selected.append(word)
        else:
            anchor_key = word_key(anchor_word)
            cursor_key = word_key(cursor_word)
            for word in words:
                current_line = line_id(word)
                current_key = word_key(word)
                if current_line == cursor_line:
                    if current_key >= cursor_key:
                        selected.append(word)
                elif current_line == anchor_line:
                    if current_key <= anchor_key:
                        selected.append(word)
                elif cursor_line < current_line < anchor_line:
                    selected.append(word)

        if not selected:
            return None, [], "", []

        selected.sort(key=word_key)
        page_rect = fitz.Rect(selected[0][:4])
        highlight_rects = self._markup_highlight_rects_from_words(selected, zoom)
        for x, y, w, h in highlight_rects:
            page_rect |= fitz.Rect(x / zoom, y / zoom, (x + w) / zoom, (y + h) / zoom)
        return page_rect, highlight_rects, self._selection_text_from_words(selected), selected

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

    def add_text_highlight(
        self,
        page_index: int,
        page_rect: fitz.Rect,
        color_rgb: tuple[float, float, float],
        *,
        selected_words: list | tuple | None = None,
        markup_group_id: str | None = None,
        origin_page_index: int | None = None,
        record_undo: bool = True,
    ) -> bool:
        """Add PDF highlight annotation for the words intersecting *page_rect*."""
        if page_rect.is_empty or page_rect.is_infinite:
            return False
        if not (0 <= page_index < len(self._doc)):
            return False

        page = self._doc[page_index]
        words = self._words_for_markup_in_rect(page, page_rect, selected_words)
        if not words:
            return False

        quads = self._word_quads_from_words(words)

        if record_undo:
            self._record_undo_checkpoint()
        annot = page.add_highlight_annot(quads)
        annot.set_colors(stroke=color_rgb)
        annot.set_opacity(0.45)
        if markup_group_id is not None and origin_page_index is not None:
            annot.set_info(
                title=PdfDocument._markup_group_title(markup_group_id, origin_page_index)
            )
        annot.update()
        if record_undo:
            self._touch()
        return True

    def recolor_text_highlights_in_rect(
        self,
        page_index: int,
        page_rect: fitz.Rect,
        color_rgb: tuple[float, float, float],
    ) -> bool:
        if page_rect.is_empty or page_rect.is_infinite:
            return False
        if not (0 <= page_index < len(self._doc)):
            return False
        page = self._doc[page_index]
        if not any(
            annot.type[0] == fitz.PDF_ANNOT_HIGHLIGHT
            and self._highlight_annot_page_rect(annot).intersects(page_rect)
            for annot in PdfDocument._iter_page_annots(page)
        ):
            return False
        if not self._restoring_history:
            self._undo_stack.append(self._snapshot_bytes())
            if len(self._undo_stack) > _MAX_UNDO_LEVELS:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
        page = self._doc[page_index]
        for annot in PdfDocument._iter_page_annots(page):
            if annot.type[0] != fitz.PDF_ANNOT_HIGHLIGHT:
                continue
            if not self._highlight_annot_page_rect(annot).intersects(page_rect):
                continue
            annot.set_colors(stroke=color_rgb)
            annot.set_opacity(0.45)
            annot.update()
        self._touch()
        return True

    def set_text_highlight_color(
        self,
        page_index: int,
        page_rect: fitz.Rect,
        color_rgb: tuple[float, float, float],
        *,
        selected_words: list | tuple | None = None,
    ) -> bool:
        """Recolor intersecting highlights, or add a new highlight when none exist."""
        if self.has_text_highlight_in_rect(page_index, page_rect):
            return self.recolor_text_highlights_in_rect(page_index, page_rect, color_rgb)
        return self.add_text_highlight(
            page_index,
            page_rect,
            color_rgb,
            selected_words=selected_words,
        )

    def get_page_text_highlight_overlays(
        self,
        page_index: int,
        zoom: float,
    ) -> list[tuple[fitz.Rect, tuple[float, float, float]]]:
        """Return highlight annotation bounds and RGB (0..1) for overlay drawing."""
        if not (0 <= page_index < len(self._doc)):
            return []
        page = self._doc[page_index]
        overlays: list[tuple[fitz.Rect, tuple[float, float, float]]] = []
        for annot in PdfDocument._iter_page_annots(page):
            if annot.type[0] != fitz.PDF_ANNOT_HIGHLIGHT:
                continue
            colors = annot.colors or {}
            stroke = colors.get("stroke") or colors.get("fill") or (1.0, 1.0, 0.0)
            rgb = tuple(float(value) for value in stroke[:3])
            vertices = annot.vertices
            if not vertices:
                rect = annot.rect
                if not rect.is_empty:
                    overlays.append(
                        (
                            fitz.Rect(
                                rect.x0 * zoom,
                                rect.y0 * zoom,
                                rect.x1 * zoom,
                                rect.y1 * zoom,
                            ),
                            rgb,
                        )
                    )
                continue
            for index in range(0, len(vertices), 4):
                quad_points = vertices[index : index + 4]
                if len(quad_points) < 4:
                    continue
                xs = [point[0] for point in quad_points]
                ys = [point[1] for point in quad_points]
                page_rect = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
                overlays.append(
                    (
                        fitz.Rect(
                            page_rect.x0 * zoom,
                            page_rect.y0 * zoom,
                            page_rect.x1 * zoom,
                            page_rect.y1 * zoom,
                        ),
                        rgb,
                    )
                )
        return overlays

    @staticmethod
    def _iter_page_annots(page):
        """Yield each page annotation once; some PDFs expose the same xref twice."""
        seen_xrefs: set[int] = set()
        for annot in page.annots() or []:
            try:
                xref = annot.xref
            except (RuntimeError, ValueError):
                continue
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            yield annot

    @staticmethod
    def _highlight_annot_page_rect(annot) -> fitz.Rect:
        vertices = annot.vertices
        if vertices:
            xs = [point[0] for point in vertices]
            ys = [point[1] for point in vertices]
            return fitz.Rect(min(xs), min(ys), max(xs), max(ys))
        return annot.rect

    @staticmethod
    def _highlight_annot_contains_point(annot, point: fitz.Point) -> bool:
        if annot.type[0] != fitz.PDF_ANNOT_HIGHLIGHT:
            return False
        vertices = annot.vertices
        if vertices:
            for index in range(0, len(vertices), 4):
                quad_points = vertices[index : index + 4]
                if len(quad_points) < 4:
                    continue
                xs = [point_tuple[0] for point_tuple in quad_points]
                ys = [point_tuple[1] for point_tuple in quad_points]
                quad_rect = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
                if quad_rect.contains(point):
                    return True
            return False
        return annot.rect.contains(point)

    @staticmethod
    def _highlight_annot_quad_rects(annot) -> list[fitz.Rect]:
        vertices = annot.vertices
        if not vertices:
            if annot.rect.is_empty:
                return []
            return [annot.rect]
        quad_rects: list[fitz.Rect] = []
        for index in range(0, len(vertices), 4):
            quad_points = vertices[index : index + 4]
            if len(quad_points) < 4:
                continue
            xs = [point[0] for point in quad_points]
            ys = [point[1] for point in quad_points]
            quad_rects.append(fitz.Rect(min(xs), min(ys), max(xs), max(ys)))
        return quad_rects

    @staticmethod
    def _markup_group_title(group_id: str, origin_page_index: int) -> str:
        return f"{_MARKUP_GROUP_TITLE_PREFIX}{group_id};o={origin_page_index}"

    @staticmethod
    def _parse_markup_group_title(title: str) -> tuple[str | None, int | None]:
        if not title.startswith(_MARKUP_GROUP_TITLE_PREFIX):
            return None, None
        group_id: str | None = None
        origin_page: int | None = None
        for token in title.split(";"):
            if token.startswith(_MARKUP_GROUP_TITLE_PREFIX):
                group_id = token[len(_MARKUP_GROUP_TITLE_PREFIX) :]
            elif token.startswith("o="):
                try:
                    origin_page = int(token[2:])
                except ValueError:
                    origin_page = None
        return group_id, origin_page

    def apply_text_markup_to_pages(
        self,
        page_targets: list[tuple[int, fitz.Rect, tuple[tuple, ...] | None]],
        *,
        kind: str,
        color_rgb: tuple[float, float, float],
        origin_page_index: int,
    ) -> bool:
        """Apply highlight/underline to multiple pages as one grouped markup."""
        if not page_targets:
            return False
        group_id = uuid.uuid4().hex[:12]
        self._record_undo_checkpoint()
        applied = False
        for page_index, page_rect, selected_words in page_targets:
            if kind == "underline":
                ok = self.add_text_underline(
                    page_index,
                    page_rect,
                    color_rgb,
                    selected_words=selected_words,
                    markup_group_id=group_id,
                    origin_page_index=origin_page_index,
                    record_undo=False,
                )
            else:
                ok = self.add_text_highlight(
                    page_index,
                    page_rect,
                    color_rgb,
                    selected_words=selected_words,
                    markup_group_id=group_id,
                    origin_page_index=origin_page_index,
                    record_undo=False,
                )
            applied = applied or ok
        if applied:
            self._touch()
        return applied

    @staticmethod
    def _markup_text_from_annot(page, annot) -> str:
        page_rect = PdfDocument._highlight_annot_page_rect(annot)
        quad_rects = PdfDocument._highlight_annot_quad_rects(annot)
        words = PdfDocument._words_from_highlight_quads(page, quad_rects)
        if not words:
            words = PdfDocument._words_in_reading_order(page, page_rect)
            centered = [
                word
                for word in words
                if PdfDocument._word_center_in_rect(word, page_rect)
            ]
            if centered:
                words = centered
        if words:
            text = PdfDocument._selection_text_from_words(words).strip()
            if text:
                return text
        if quad_rects:
            text_parts: list[str] = []
            for quad_rect in quad_rects:
                part = page.get_text("text", clip=quad_rect).strip()
                if part:
                    text_parts.append(part)
            if text_parts:
                return PdfDocument._plain_text_to_markup_text("\n".join(text_parts))
        text = page.get_text("text", clip=page_rect).strip()
        if text:
            return PdfDocument._plain_text_to_markup_text(text)
        return PdfDocument._plain_text_to_markup_text((annot.get_text() or "").strip())

    @staticmethod
    def _markup_rgb_from_annot(annot, *, default: tuple[float, float, float]) -> tuple[float, float, float]:
        colors = annot.colors or {}
        stroke = colors.get("stroke") or colors.get("fill") or default
        return tuple(float(value) for value in stroke[:3])

    def get_text_markup_entries(self) -> list[TextMarkupEntry]:
        """Return highlight/underline annotations sorted by page and position."""
        grouped: dict[tuple[str, str], list[tuple[int, int, str, tuple[float, float, float], float, float]]] = {}
        singles: list[TextMarkupEntry] = []

        for page_index in range(len(self._doc)):
            page = self._doc[page_index]
            for annot in PdfDocument._iter_page_annots(page):
                annot_type = annot.type[0]
                if annot_type == fitz.PDF_ANNOT_HIGHLIGHT:
                    kind = "highlight"
                    default_rgb = (1.0, 1.0, 0.0)
                elif annot_type == fitz.PDF_ANNOT_UNDERLINE:
                    kind = "underline"
                    default_rgb = (1.0, 0.0, 0.0)
                else:
                    continue
                text = self._markup_text_from_annot(page, annot).strip()
                if not text:
                    continue
                page_rect = self._highlight_annot_page_rect(annot)
                rgb = self._markup_rgb_from_annot(annot, default=default_rgb)
                title = (annot.info or {}).get("title") or ""
                group_id, origin_page = self._parse_markup_group_title(title)
                if group_id is not None and origin_page is not None:
                    grouped.setdefault((group_id, kind), []).append(
                        (origin_page, page_index, text, rgb, page_rect.y0, page_rect.x0)
                    )
                else:
                    singles.append(
                        TextMarkupEntry(
                            page_index=page_index,
                            text=text,
                            kind=kind,
                            rgb=rgb,
                            sort_y=page_rect.y0,
                            sort_x=page_rect.x0,
                            page_rect=page_rect,
                        )
                    )

        entries: list[TextMarkupEntry] = list(singles)
        for (_group_id, kind), items in grouped.items():
            items.sort(key=lambda item: (item[1], item[4], item[5]))
            origin_page = items[0][0]
            merged_text = PdfDocument._join_continued_text_parts(
                [item[2] for item in items]
            )
            rgb = items[0][3]
            entries.append(
                TextMarkupEntry(
                    page_index=origin_page,
                    text=merged_text,
                    kind=kind,
                    rgb=rgb,
                    sort_y=items[0][4],
                    sort_x=items[0][5],
                    group_id=_group_id,
                )
            )
        entries.sort(key=lambda entry: (entry.page_index, entry.sort_y, entry.sort_x))
        return entries

    def _markup_metadata_at_point(
        self,
        page_index: int,
        point: fitz.Point,
    ) -> tuple[str, fitz.Rect, str | None] | None:
        if not (0 <= page_index < len(self._doc)):
            return None
        page = self._doc[page_index]
        hit = fitz.Rect(point.x - 2, point.y - 2, point.x + 2, point.y + 2)
        for preferred_type in (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE):
            for annot in PdfDocument._iter_page_annots(page):
                try:
                    annot_type = annot.type[0]
                except (RuntimeError, ValueError):
                    continue
                if annot_type != preferred_type:
                    continue
                page_rect = self._highlight_annot_page_rect(annot)
                if not page_rect.intersects(hit):
                    continue
                kind = "underline" if annot_type == fitz.PDF_ANNOT_UNDERLINE else "highlight"
                title = (annot.info or {}).get("title") or ""
                group_id, _ = self._parse_markup_group_title(title)
                return kind, page_rect, group_id
        return None

    @staticmethod
    def _text_markup_entries_match(
        left: TextMarkupEntry,
        right: TextMarkupEntry,
    ) -> bool:
        if left.kind != right.kind:
            return False
        if left.group_id or right.group_id:
            return left.group_id == right.group_id
        if left.page_index != right.page_index:
            return False
        if left.page_rect is None or right.page_rect is None:
            return False
        return left.page_rect.intersects(right.page_rect)

    def find_text_markup_entry_at_point(
        self,
        page_index: int,
        point: fitz.Point,
    ) -> TextMarkupEntry | None:
        """Return the sidebar list entry for the markup annotation at *point*."""
        metadata = self._markup_metadata_at_point(page_index, point)
        if metadata is None:
            return None
        kind, page_rect, group_id = metadata
        for entry in self.get_text_markup_entries():
            if entry.kind != kind:
                continue
            if group_id is not None and entry.group_id == group_id:
                return entry
            if (
                group_id is None
                and entry.group_id is None
                and entry.page_index == page_index
                and entry.page_rect is not None
                and entry.page_rect.intersects(page_rect)
            ):
                return entry
        return None

    def get_text_markup_selection_for_rect(
        self,
        page_index: int,
        page_rect: fitz.Rect,
        kind: str,
    ) -> tuple[fitz.Rect, list[fitz.Rect], str] | None:
        if page_rect.is_empty or page_rect.is_infinite:
            return None
        if not (0 <= page_index < len(self._doc)):
            return None
        annot_type = (
            fitz.PDF_ANNOT_UNDERLINE if kind == "underline" else fitz.PDF_ANNOT_HIGHLIGHT
        )
        page = self._doc[page_index]
        best: tuple[fitz.Rect, list[fitz.Rect], str] | None = None
        best_area = -1.0
        for annot in PdfDocument._iter_page_annots(page):
            try:
                if annot.type[0] != annot_type:
                    continue
            except (RuntimeError, ValueError):
                continue
            rect = self._highlight_annot_page_rect(annot)
            if not rect.intersects(page_rect):
                continue
            area = rect.get_area()
            if area <= best_area:
                continue
            quad_rects = self._highlight_annot_quad_rects(annot)
            if not quad_rects:
                continue
            text = self._markup_text_from_annot(page, annot)
            best = (rect, quad_rects, text)
            best_area = area
        return best

    def collect_text_markup_group_segments(
        self,
        group_id: str,
        kind: str,
    ) -> list[PageSelectionSegment]:
        annot_type = (
            fitz.PDF_ANNOT_UNDERLINE if kind == "underline" else fitz.PDF_ANNOT_HIGHLIGHT
        )
        segments: list[PageSelectionSegment] = []
        for page_index in range(len(self._doc)):
            page = self._doc[page_index]
            for annot in PdfDocument._iter_page_annots(page):
                try:
                    if annot.type[0] != annot_type:
                        continue
                except (RuntimeError, ValueError):
                    continue
                title = (annot.info or {}).get("title") or ""
                parsed_group_id, _ = self._parse_markup_group_title(title)
                if parsed_group_id != group_id:
                    continue
                page_rect = self._highlight_annot_page_rect(annot)
                text = self._markup_text_from_annot(page, annot)
                segments.append(
                    PageSelectionSegment(page_index, page_rect, text)
                )
        segments.sort(key=lambda segment: segment.page_index)
        return segments

    @staticmethod
    def _delete_page_annots_by_xrefs(page, xrefs: set[int]) -> int:
        """Delete annotations by xref, re-resolving each annot from the page."""
        remaining = set(xrefs)
        deleted = 0
        while remaining:
            deleted_one = False
            for annot in PdfDocument._iter_page_annots(page):
                if annot.xref not in remaining:
                    continue
                page.delete_annot(annot)
                remaining.discard(annot.xref)
                deleted += 1
                deleted_one = True
                break
            if not deleted_one:
                break
        return deleted

    def remove_text_markup_entry(self, entry: TextMarkupEntry) -> bool:
        """Remove the highlight or underline represented by a panel list entry."""
        if entry.group_id:
            return self._remove_text_markup_group(entry.group_id, entry.kind)
        if entry.page_rect is None or entry.page_rect.is_empty:
            return False
        if entry.kind == "underline":
            return self.remove_text_underlines_in_rect(entry.page_index, entry.page_rect)
        return self.remove_text_highlights_in_rect(entry.page_index, entry.page_rect)

    def _remove_text_markup_group(self, group_id: str, kind: str) -> bool:
        if kind == "underline":
            annot_type = fitz.PDF_ANNOT_UNDERLINE
        else:
            annot_type = fitz.PDF_ANNOT_HIGHLIGHT
        to_delete: dict[int, set[int]] = {}
        for page_index in range(len(self._doc)):
            page = self._doc[page_index]
            for annot in PdfDocument._iter_page_annots(page):
                try:
                    if annot.type[0] != annot_type:
                        continue
                except (RuntimeError, ValueError):
                    continue
                title = (annot.info or {}).get("title") or ""
                parsed_group_id, _ = self._parse_markup_group_title(title)
                if parsed_group_id != group_id:
                    continue
                to_delete.setdefault(page_index, set()).add(annot.xref)
        if not to_delete:
            return False
        self._record_undo_checkpoint()
        for page_index, xrefs in to_delete.items():
            page = self._doc[page_index]
            self._delete_page_annots_by_xrefs(page, xrefs)
        self._touch()
        return True

    def _find_highlight_selection_at_point(
        self,
        page_index: int,
        point: fitz.Point,
    ) -> tuple[fitz.Rect, list[fitz.Rect], str] | None:
        """Return page rect, per-quad rects, and text for the highlight at *point*."""
        if not (0 <= page_index < len(self._doc)):
            return None
        page = self._doc[page_index]
        hit = fitz.Rect(point.x - 2, point.y - 2, point.x + 2, point.y + 2)
        for annot in PdfDocument._iter_page_annots(page):
            if annot.type[0] != fitz.PDF_ANNOT_HIGHLIGHT:
                continue
            page_rect = self._highlight_annot_page_rect(annot)
            if not page_rect.intersects(hit):
                continue
            quad_rects = self._highlight_annot_quad_rects(annot)
            if not quad_rects:
                continue
            selected_text = self._markup_text_from_annot(page, annot)
            return page_rect, quad_rects, selected_text
        return None

    def get_text_highlight_selection_at_point(
        self,
        page_index: int,
        point: fitz.Point,
    ) -> tuple[fitz.Rect, list[fitz.Rect], str] | None:
        return self._find_highlight_selection_at_point(page_index, point)

    def find_text_highlight_at_point(
        self,
        page_index: int,
        point: fitz.Point,
    ) -> fitz.Rect | None:
        selection = self._find_highlight_selection_at_point(page_index, point)
        if selection is None:
            return None
        return selection[0]

    def has_text_highlight_in_rect(self, page_index: int, page_rect: fitz.Rect) -> bool:
        if page_rect.is_empty or page_rect.is_infinite:
            return False
        if not (0 <= page_index < len(self._doc)):
            return False
        page = self._doc[page_index]
        for annot in PdfDocument._iter_page_annots(page):
            if annot.type[0] != fitz.PDF_ANNOT_HIGHLIGHT:
                continue
            if self._highlight_annot_page_rect(annot).intersects(page_rect):
                return True
        return False

    def remove_text_highlights_in_rect(self, page_index: int, page_rect: fitz.Rect) -> bool:
        if page_rect.is_empty or page_rect.is_infinite:
            return False
        if not (0 <= page_index < len(self._doc)):
            return False
        page = self._doc[page_index]
        if not any(
            annot.type[0] == fitz.PDF_ANNOT_HIGHLIGHT
            and self._highlight_annot_page_rect(annot).intersects(page_rect)
            for annot in PdfDocument._iter_page_annots(page)
        ):
            return False
        if not self._restoring_history:
            self._record_undo_checkpoint()
        page = self._doc[page_index]
        xrefs = {
            annot.xref
            for annot in PdfDocument._iter_page_annots(page)
            if annot.type[0] == fitz.PDF_ANNOT_HIGHLIGHT
            and self._highlight_annot_page_rect(annot).intersects(page_rect)
        }
        self._delete_page_annots_by_xrefs(page, xrefs)
        self._touch()
        return True

    def _word_quads_in_rect(
        self,
        page,
        page_rect: fitz.Rect,
        selected_words: list | tuple | None = None,
    ) -> list[fitz.Quad]:
        words = self._words_for_markup_in_rect(page, page_rect, selected_words)
        return self._word_quads_from_words(words)

    def add_text_underline(
        self,
        page_index: int,
        page_rect: fitz.Rect,
        color_rgb: tuple[float, float, float],
        *,
        selected_words: list | tuple | None = None,
        markup_group_id: str | None = None,
        origin_page_index: int | None = None,
        record_undo: bool = True,
    ) -> bool:
        if page_rect.is_empty or page_rect.is_infinite:
            return False
        if not (0 <= page_index < len(self._doc)):
            return False
        page = self._doc[page_index]
        quads = self._word_quads_in_rect(page, page_rect, selected_words)
        if not quads:
            return False
        if record_undo:
            self._record_undo_checkpoint()
        annot = page.add_underline_annot(quads)
        annot.set_colors(stroke=color_rgb)
        if markup_group_id is not None and origin_page_index is not None:
            annot.set_info(
                title=PdfDocument._markup_group_title(markup_group_id, origin_page_index)
            )
        annot.update()
        if record_undo:
            self._touch()
        return True

    def recolor_text_underlines_in_rect(
        self,
        page_index: int,
        page_rect: fitz.Rect,
        color_rgb: tuple[float, float, float],
    ) -> bool:
        if page_rect.is_empty or page_rect.is_infinite:
            return False
        if not (0 <= page_index < len(self._doc)):
            return False
        page = self._doc[page_index]
        if not any(
            annot.type[0] == fitz.PDF_ANNOT_UNDERLINE
            and self._highlight_annot_page_rect(annot).intersects(page_rect)
            for annot in PdfDocument._iter_page_annots(page)
        ):
            return False
        if not self._restoring_history:
            self._undo_stack.append(self._snapshot_bytes())
            if len(self._undo_stack) > _MAX_UNDO_LEVELS:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
        page = self._doc[page_index]
        for annot in PdfDocument._iter_page_annots(page):
            if annot.type[0] != fitz.PDF_ANNOT_UNDERLINE:
                continue
            if not self._highlight_annot_page_rect(annot).intersects(page_rect):
                continue
            annot.set_colors(stroke=color_rgb)
            annot.update()
        self._touch()
        return True

    def set_text_underline_color(
        self,
        page_index: int,
        page_rect: fitz.Rect,
        color_rgb: tuple[float, float, float],
        *,
        selected_words: list | tuple | None = None,
    ) -> bool:
        if self.has_text_underline_in_rect(page_index, page_rect):
            return self.recolor_text_underlines_in_rect(page_index, page_rect, color_rgb)
        return self.add_text_underline(
            page_index,
            page_rect,
            color_rgb,
            selected_words=selected_words,
        )

    def get_page_text_underline_overlays(
        self,
        page_index: int,
        zoom: float,
    ) -> list[tuple[tuple[float, float, float, float], tuple[float, float, float]]]:
        if not (0 <= page_index < len(self._doc)):
            return []
        page = self._doc[page_index]
        overlays: list[
            tuple[tuple[float, float, float, float], tuple[float, float, float]]
        ] = []
        for annot in PdfDocument._iter_page_annots(page):
            if annot.type[0] != fitz.PDF_ANNOT_UNDERLINE:
                continue
            colors = annot.colors or {}
            stroke = colors.get("stroke") or colors.get("fill") or (1.0, 0.0, 0.0)
            rgb = tuple(float(value) for value in stroke[:3])
            for quad_rect in self._highlight_annot_quad_rects(annot):
                y_bottom = quad_rect.y1 * zoom
                overlays.append(
                    (
                        (
                            quad_rect.x0 * zoom,
                            y_bottom,
                            quad_rect.x1 * zoom,
                            y_bottom,
                        ),
                        rgb,
                    )
                )
        return overlays

    def _find_underline_selection_at_point(
        self,
        page_index: int,
        point: fitz.Point,
    ) -> tuple[fitz.Rect, list[fitz.Rect], str] | None:
        if not (0 <= page_index < len(self._doc)):
            return None
        page = self._doc[page_index]
        hit = fitz.Rect(point.x - 2, point.y - 2, point.x + 2, point.y + 2)
        for annot in PdfDocument._iter_page_annots(page):
            if annot.type[0] != fitz.PDF_ANNOT_UNDERLINE:
                continue
            page_rect = self._highlight_annot_page_rect(annot)
            if not page_rect.intersects(hit):
                continue
            quad_rects = self._highlight_annot_quad_rects(annot)
            if not quad_rects:
                continue
            selected_text = self._markup_text_from_annot(page, annot)
            return page_rect, quad_rects, selected_text
        return None

    def get_text_underline_selection_at_point(
        self,
        page_index: int,
        point: fitz.Point,
    ) -> tuple[fitz.Rect, list[fitz.Rect], str] | None:
        return self._find_underline_selection_at_point(page_index, point)

    def has_text_underline_in_rect(self, page_index: int, page_rect: fitz.Rect) -> bool:
        if page_rect.is_empty or page_rect.is_infinite:
            return False
        if not (0 <= page_index < len(self._doc)):
            return False
        page = self._doc[page_index]
        for annot in PdfDocument._iter_page_annots(page):
            if annot.type[0] != fitz.PDF_ANNOT_UNDERLINE:
                continue
            if self._highlight_annot_page_rect(annot).intersects(page_rect):
                return True
        return False

    def remove_text_underlines_in_rect(self, page_index: int, page_rect: fitz.Rect) -> bool:
        if page_rect.is_empty or page_rect.is_infinite:
            return False
        if not (0 <= page_index < len(self._doc)):
            return False
        page = self._doc[page_index]
        if not any(
            annot.type[0] == fitz.PDF_ANNOT_UNDERLINE
            and self._highlight_annot_page_rect(annot).intersects(page_rect)
            for annot in PdfDocument._iter_page_annots(page)
        ):
            return False
        if not self._restoring_history:
            self._record_undo_checkpoint()
        page = self._doc[page_index]
        xrefs = {
            annot.xref
            for annot in PdfDocument._iter_page_annots(page)
            if annot.type[0] == fitz.PDF_ANNOT_UNDERLINE
            and self._highlight_annot_page_rect(annot).intersects(page_rect)
        }
        self._delete_page_annots_by_xrefs(page, xrefs)
        self._touch()
        return True

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

    @staticmethod
    def _render_failed_after_mupdf() -> bool:
        warnings = fitz.TOOLS.mupdf_warnings(reset=True).lower()
        return any(token in warnings for token in ("corrupt", "format error", "cannot read"))

    def render_page_pixmap(self, index: int, zoom: float = 1.0) -> fitz.Pixmap:
        if self.rendering_paused:
            raise RuntimeError("rendering paused")
        page = self._doc[index]
        matrix = fitz.Matrix(zoom, zoom)
        try:
            fitz.TOOLS.mupdf_warnings(reset=True)
            pix = page.get_pixmap(matrix=matrix, alpha=False, annots=False)
            if self._render_failed_after_mupdf():
                return self._blank_page_pixmap(page.rect.width, page.rect.height, zoom)
            return pix
        except Exception:
            fitz.TOOLS.mupdf_warnings(reset=True)
            return self._blank_page_pixmap(page.rect.width, page.rect.height, zoom)

    def render_thumbnail_pixmap(self, index: int, max_width: int = 120) -> fitz.Pixmap:
        if self.rendering_paused:
            raise RuntimeError("rendering paused")
        page = self._doc[index]
        scale = max_width / page.rect.width
        matrix = fitz.Matrix(scale, scale)
        try:
            fitz.TOOLS.mupdf_warnings(reset=True)
            pix = page.get_pixmap(matrix=matrix, alpha=False, annots=False)
            if self._render_failed_after_mupdf():
                return self._blank_page_pixmap(page.rect.width, page.rect.height, scale)
            return pix
        except Exception:
            fitz.TOOLS.mupdf_warnings(reset=True)
            return self._blank_page_pixmap(page.rect.width, page.rect.height, scale)

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

    def insert_files_at(
        self,
        index: int,
        file_paths: list[str],
        *,
        record_undo: bool = True,
        resolve_pdf_password: Callable[[str, bool], str | None] | None = None,
    ) -> int:
        """Insert PDF pages or images at *index*. Returns number of pages added."""
        index = max(0, min(index, len(self._doc)))
        if not file_paths:
            return 0
        was_empty = len(self._doc) == 0
        added = 0
        for file_path in file_paths:
            ext = Path(file_path).suffix.lower()
            if ext not in PDF_EXTENSIONS and ext not in IMAGE_EXTENSIONS:
                continue
            if record_undo and added == 0:
                self._record_undo_checkpoint()
            if ext in PDF_EXTENSIONS:
                added += self._insert_pdf_at(
                    index + added,
                    file_path,
                    resolve_pdf_password=resolve_pdf_password,
                )
            elif ext in IMAGE_EXTENSIONS:
                self._insert_image_at(index + added, file_path)
                added += 1
        if added:
            self._touch()
            if was_empty and self._source_path is None:
                pdf_paths = [
                    str(Path(path).resolve())
                    for path in file_paths
                    if Path(path).suffix.lower() in PDF_EXTENSIONS
                ]
                if len(pdf_paths) == 1:
                    self._source_path = pdf_paths[0]
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

    def _insert_pdf_at(
        self,
        index: int,
        pdf_path: str,
        *,
        password: str | None = None,
        resolve_pdf_password: Callable[[str, bool], str | None] | None = None,
    ) -> int:
        pdf_bytes = Path(pdf_path).read_bytes()
        file_had_encryption = PdfDocument._pdf_bytes_encrypted(pdf_bytes)
        while True:
            try:
                src = PdfDocument._open_pdf_bytes(pdf_bytes, password=password)
                break
            except PdfPasswordRejected:
                if resolve_pdf_password is None:
                    raise
                password = resolve_pdf_password(pdf_path, True)
                if password is None:
                    return 0
            except PdfPasswordRequired:
                if resolve_pdf_password is None:
                    raise
                password = resolve_pdf_password(pdf_path, False)
                if password is None:
                    return 0
        try:
            if (
                file_had_encryption
                or password is not None
                or PdfDocument._metadata_shows_encryption(src)
            ):
                self._source_had_encryption = True
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
            out.save(path, **self._save_kwargs())
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
