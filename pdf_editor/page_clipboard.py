"""In-memory page clipboard for copy/cut/paste between document tabs."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QMimeData
from PyQt6.QtWidgets import QApplication

PAGE_CLIPBOARD_MIME = "application/x-tiny-pdf-editor-pages"


@dataclass(frozen=True)
class PageClipboardPayload:
    pdf_bytes: bytes
    page_count: int


class PageClipboard:
    """App-wide clipboard holding copied/cut PDF page payloads."""

    _payload: PageClipboardPayload | None = None

    @classmethod
    def set_pages(cls, pdf_bytes: bytes, page_count: int) -> None:
        cls._payload = PageClipboardPayload(pdf_bytes, page_count)
        if QApplication.instance() is None:
            return
        mime = QMimeData()
        mime.setData(PAGE_CLIPBOARD_MIME, pdf_bytes)
        QApplication.clipboard().setMimeData(mime)

    @classmethod
    def has_pages(cls) -> bool:
        if cls._payload is not None:
            return True
        mime = QApplication.clipboard().mimeData()
        return mime is not None and mime.hasFormat(PAGE_CLIPBOARD_MIME)

    @classmethod
    def page_count(cls) -> int:
        if cls._payload is not None:
            return cls._payload.page_count
        payload = cls.get_payload()
        if payload is None:
            return 0
        return payload.page_count

    @classmethod
    def get_payload(cls) -> PageClipboardPayload | None:
        if cls._payload is not None:
            return cls._payload
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(PAGE_CLIPBOARD_MIME):
            return None
        pdf_bytes = bytes(mime.data(PAGE_CLIPBOARD_MIME))
        if not pdf_bytes:
            return None
        try:
            import fitz

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                count = len(doc)
            finally:
                doc.close()
        except Exception:
            return None
        cls._payload = PageClipboardPayload(pdf_bytes, count)
        return cls._payload

    @classmethod
    def clear(cls) -> None:
        cls._payload = None
