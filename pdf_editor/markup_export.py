"""Export highlight/underline entries for Excel."""

from __future__ import annotations

import csv
from pathlib import Path

from pdf_editor.document import TextMarkupEntry


def export_markup_entries_to_csv(entries: list[TextMarkupEntry], path: str | Path) -> None:
    """Write *entries* as UTF-8 CSV with header row [페이지, 내용]."""
    target = Path(path)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["페이지", "내용"])
        for entry in entries:
            writer.writerow([entry.page_index + 1, entry.text])
