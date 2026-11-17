"""Per-file progress and cancel checkpoints for long operations (insert / export images)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from pdf_editor.document import PdfDocument


def _pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for n in range(pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 50), f"P{n + 1}")
    doc.save(str(path))
    doc.close()


class ProgressCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.files = []
        for n in range(4):
            path = self.dir / f"f{n}.pdf"
            _pdf(path, 2)
            self.files.append(str(path))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_insert_reports_each_file(self) -> None:
        doc = PdfDocument()
        doc.new_document()
        events: list[tuple[int, int, str]] = []
        added = doc.insert_files_at(0, self.files, progress=lambda d, t, n: events.append((d, t, n)))
        self.assertEqual(added, 8)
        self.assertEqual([e[:2] for e in events], [(0, 4), (1, 4), (2, 4), (3, 4), (4, 4)])
        self.assertEqual(events[0][2], "f0.pdf")
        self.assertEqual(events[-1][2], "")

    def test_insert_stops_between_files_and_keeps_done_files(self) -> None:
        doc = PdfDocument()
        doc.new_document()
        done: list[int] = []
        added = doc.insert_files_at(
            0,
            self.files,
            progress=lambda d, t, n: done.append(d),
            should_cancel=lambda: len(done) >= 2,
        )
        self.assertEqual(added, 4)
        self.assertEqual(doc.page_count, 4)

    def test_export_stops_when_cancelled(self) -> None:
        doc = PdfDocument()
        doc.new_document()
        doc.insert_files_at(0, self.files)
        seen: list[int] = []
        out = self.dir / "out"
        doc.export_document_as_images(
            out,
            dpi=50,
            progress=lambda d, t: seen.append(d),
            should_cancel=lambda: len(seen) >= 3,
        )
        self.assertEqual(len(list(out.glob("*.png"))), 3)

    def test_export_pages_cancelled_before_first_page_is_not_an_error(self) -> None:
        doc = PdfDocument()
        doc.new_document()
        doc.insert_files_at(0, self.files)
        saved = doc.export_pages_as_images([0, 1], str(self.dir / "p"), should_cancel=lambda: True)
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
