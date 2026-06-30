"""Multi-page text selection state for cross-page highlight/underline."""

from __future__ import annotations

from dataclasses import dataclass, field

import fitz


@dataclass
class PageSelectionSegment:
    page_index: int
    page_rect: fitz.Rect
    text: str
    words: tuple[tuple, ...] = ()


@dataclass
class CrossPageSelection:
    origin_page_index: int
    segments: dict[int, PageSelectionSegment] = field(default_factory=dict)

    def combined_text(self) -> str:
        return " ".join(
            self.segments[index].text.strip()
            for index in sorted(self.segments)
            if self.segments[index].text.strip()
        )

    def page_rects(self) -> list[tuple[int, fitz.Rect]]:
        return [
            (index, self.segments[index].page_rect)
            for index in sorted(self.segments)
        ]

    def page_targets(self) -> list[tuple[int, fitz.Rect, tuple[tuple, ...] | None]]:
        return [
            (
                index,
                self.segments[index].page_rect,
                self.segments[index].words or None,
            )
            for index in sorted(self.segments)
        ]

    def set_segment(self, segment: PageSelectionSegment) -> None:
        self.segments[segment.page_index] = segment
