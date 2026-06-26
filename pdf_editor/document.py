"""PDF document model backed by PyMuPDF."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

import fitz

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
PDF_EXTENSIONS = {".pdf"}


@dataclass(frozen=True)
class SearchHit:
    page_index: int
    rect: fitz.Rect


class PdfDocument:
    """In-memory PDF with page insert, delete, rotate, and export operations."""

    def __init__(self) -> None:
        self._doc = fitz.open()
        self._source_path: str | None = None
        self._modified = False

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
                self._doc.save(str(staging), garbage=4, deflate=True)
                os.replace(str(staging), target)
            except Exception:
                staging.unlink(missing_ok=True)
                raise
        else:
            self._doc.save(target, garbage=4, deflate=True)

        self._source_path = target
        self._modified = False
        return target

    def save_to_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self._doc.save(buffer, garbage=4, deflate=True, use_objstms=True)
        return buffer.getvalue()

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
        page = self._doc[index]
        matrix = fitz.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=matrix, alpha=False, annots=False)

    def render_thumbnail_pixmap(self, index: int, max_width: int = 120) -> fitz.Pixmap:
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
            out.save(path, garbage=4, deflate=True)
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
