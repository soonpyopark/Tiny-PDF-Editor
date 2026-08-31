#!/usr/bin/env python3
"""Download PP-OCR Korean, English, and Chinese ONNX models into a folder."""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

MODELS: list[tuple[str, list[str]]] = [
    (
        "ch_PP-OCRv5_det_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx",
        ],
    ),
    (
        "korean_PP-OCRv5_rec_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx",
        ],
    ),
    (
        "en_PP-OCRv5_rec_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/en_PP-OCRv5_rec_mobile.onnx",
        ],
    ),
    (
        "ch_PP-OCRv5_rec_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx",
        ],
    ),
    (
        "ppocrv5_dict.txt",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile/ppocrv5_dict.txt",
        ],
    ),
    (
        "ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/cls/ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx",
        ],
    ),
    (
        "ppocrv5_korean_dict.txt",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile/ppocrv5_korean_dict.txt",
        ],
    ),
    (
        "en_dict.txt",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile/en_dict.txt",
        ],
    ),
    (
        "ch_PP-OCRv4_det_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/det/ch_PP-OCRv4_det_mobile.onnx",
            "https://huggingface.co/datasets/SWHL/RapidOCR/resolve/main/onnx/PP-OCRv4/det/ch_PP-OCRv4_det_mobile.onnx",
        ],
    ),
    (
        "korean_PP-OCRv4_rec_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/rec/korean_PP-OCRv4_rec_mobile.onnx",
            "https://huggingface.co/datasets/SWHL/RapidOCR/resolve/main/onnx/PP-OCRv4/rec/korean_PP-OCRv4_rec_mobile.onnx",
        ],
    ),
    (
        "en_PP-OCRv4_rec_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx",
            "https://huggingface.co/datasets/SWHL/RapidOCR/resolve/main/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx",
        ],
    ),
    (
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "https://huggingface.co/datasets/SWHL/RapidOCR/resolve/main/onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        ],
    ),
    (
        "korean_dict.txt",
        [
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv4/rec/korean_PP-OCRv4_rec_mobile/korean_dict.txt",
        ],
    ),
]


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TinyPDFEditor-OCR-pack/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
    tmp.replace(dest)


def _ensure_file(name: str, urls: list[str], dest_dir: Path) -> Path:
    dest = dest_dir / name
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"[ocr-models] exists: {dest.name} ({dest.stat().st_size} bytes)")
        return dest
    last_error: Exception | None = None
    for url in urls:
        try:
            print(f"[ocr-models] download {dest.name}")
            print(f"[ocr-models]   {url}")
            _download(url, dest)
            if dest.stat().st_size <= 0:
                raise OSError("empty download")
            print(f"[ocr-models] saved {dest.name} ({dest.stat().st_size} bytes)")
            return dest
        except Exception as exc:  # noqa: BLE001 — try next mirror
            last_error = exc
            print(f"[ocr-models] failed: {exc}", file=sys.stderr)
            if dest.exists():
                dest.unlink(missing_ok=True)
    raise RuntimeError(f"Could not download {name}") from last_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Korean+English+Chinese OCR models")
    parser.add_argument("--dest", required=True, help="Destination models folder")
    args = parser.parse_args()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name, urls in MODELS:
        _ensure_file(name, urls, dest)
    print(f"[ocr-models] ready: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
