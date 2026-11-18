"""Insert password-protected PDFs into an open document (thumbnail-add path)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from pdf_editor.document import PdfDocument, PdfPasswordRequired
from pdf_editor.engine import _merge_password_resolver


def _plain_pdf(path: Path, label: str = "OK") -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 50), label)
    doc.save(str(path))
    doc.close()


def _locked_pdf(path: Path, password: str, label: str = "LOCKED") -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 50), label)
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw=password,
        owner_pw=password,
        permissions=int(fitz.PDF_PERM_ACCESSIBILITY),
    )
    doc.close()


class InsertPasswordTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_insert_locked_without_password_raises_with_path(self) -> None:
        locked = self.dir / "secret.pdf"
        _locked_pdf(locked, "secret")
        doc = PdfDocument()
        doc.new_document()
        with self.assertRaises(PdfPasswordRequired) as ctx:
            doc.insert_files_at(
                0,
                [str(locked)],
                resolve_pdf_password=_merge_password_resolver({}),
            )
        self.assertEqual(getattr(ctx.exception, "path", None), str(locked))
        self.assertEqual(doc.page_count, 0)

    def test_insert_locked_with_password_adds_pages(self) -> None:
        locked = self.dir / "secret.pdf"
        plain = self.dir / "open.pdf"
        _locked_pdf(locked, "secret")
        _plain_pdf(plain)
        doc = PdfDocument()
        doc.new_document()
        added = doc.insert_files_at(
            0,
            [str(plain), str(locked)],
            resolve_pdf_password=_merge_password_resolver({str(locked): "secret"}),
        )
        self.assertEqual(added, 2)
        self.assertEqual(doc.page_count, 2)

    def test_wrong_password_raises_rejected(self) -> None:
        locked = self.dir / "secret.pdf"
        _locked_pdf(locked, "secret")
        doc = PdfDocument()
        doc.new_document()
        with self.assertRaises(PdfPasswordRequired) as ctx:
            doc.insert_files_at(
                0,
                [str(locked)],
                resolve_pdf_password=_merge_password_resolver({str(locked): "wrong"}),
            )
        self.assertTrue(getattr(ctx.exception, "path", None))


if __name__ == "__main__":
    unittest.main()
