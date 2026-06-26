"""Convert PyMuPDF pixmaps to Qt images."""

from __future__ import annotations

import fitz
from PyQt6.QtGui import QImage, QPixmap


def pixmap_from_fitz(pix: fitz.Pixmap) -> QPixmap:
    try:
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        return QPixmap.fromImage(image)
    finally:
        pix = None
