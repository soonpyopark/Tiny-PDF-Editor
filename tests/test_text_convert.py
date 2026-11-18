"""TXT / Markdown → PDF 변환·삽입."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

from pdf_editor.document import PdfDocument
from pdf_editor.text_convert import convert_text_file_to_pdf, convert_text_file_to_pdf_bytes


class TextConvertTests(unittest.TestCase):
    def test_plain_txt_korean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "note.txt"
            src.write_text("안녕하세요\n\n두 번째 문단입니다.", encoding="utf-8")
            out = root / "note.pdf"
            convert_text_file_to_pdf(src, out)
            doc = fitz.open(out)
            try:
                self.assertGreaterEqual(len(doc), 1)
                text = "".join(page.get_text() for page in doc)
                self.assertIn("안녕하세요", text)
                self.assertIn("두 번째 문단", text)
                self.assertLess(out.stat().st_size, 80_000)
            finally:
                doc.close()

    def test_markdown_renders_not_raw_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "readme.md"
            src.write_text(
                "# 제목\n\n일반 문단과 **굵게** 표시.\n\n- 첫 항목\n- 둘째 항목\n",
                encoding="utf-8",
            )
            pdf = convert_text_file_to_pdf_bytes(src)
            doc = fitz.open(stream=pdf, filetype="pdf")
            try:
                text = "".join(page.get_text() for page in doc)
                self.assertIn("제목", text)
                self.assertIn("굵게", text)
                self.assertIn("첫 항목", text)
                self.assertNotIn("**굵게**", text)
                self.assertNotIn("# 제목", text)
            finally:
                doc.close()

    def test_insert_txt_into_empty_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "memo.txt"
            src.write_text("삽입 테스트 본문", encoding="utf-8")
            doc = PdfDocument()
            try:
                added = doc.insert_files_at(0, [str(src)])
                self.assertGreaterEqual(added, 1)
                self.assertGreaterEqual(doc.page_count, 1)
            finally:
                doc.close()


if __name__ == "__main__":
    unittest.main()
