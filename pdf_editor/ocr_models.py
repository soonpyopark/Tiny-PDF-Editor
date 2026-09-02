"""Official Paddle PP-OCRv5 ONNX weights bundled with the app."""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class OcrModelSpec:
    name: str
    filename: str
    url: str
    sha256: str
    size_mb: int


OCR_DET_MODEL = OcrModelSpec(
    name="PP-OCRv5 mobile det",
    filename="det.onnx",
    url="https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/main/inference.onnx",
    sha256="a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d",
    size_mb=5,
)
OCR_REC_MODEL = OcrModelSpec(
    name="PP-OCRv5 korean rec",
    filename="rec_korean.onnx",
    url="https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.onnx",
    sha256="92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08",
    size_mb=13,
)
OCR_REC_DICT = OcrModelSpec(
    name="PP-OCRv5 korean dict",
    filename="rec_korean.yml",
    url="https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.yml",
    sha256="f757fa1c40e99edcf27e9cce879b93eb2a51fa46f5ef39095689b8c37dd75998",
    size_mb=1,
)
ALL_OCR_MODELS = (OCR_DET_MODEL, OCR_REC_MODEL, OCR_REC_DICT)


def models_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        candidates = []
        if meipass:
            candidates.append(Path(meipass) / "ocr" / "models")
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            (
                exe_dir / "ocr" / "models",
                exe_dir / "_internal" / "ocr" / "models",
            )
        )
        for folder in candidates:
            if folder.is_dir():
                return folder
        return candidates[0]
    return Path(__file__).resolve().parents[1] / "ocr" / "models"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_status(folder: Path | None = None) -> list[tuple[OcrModelSpec, bool]]:
    root = folder or models_dir()
    result: list[tuple[OcrModelSpec, bool]] = []
    for spec in ALL_OCR_MODELS:
        path = root / spec.filename
        ok = path.is_file() and _file_sha256(path) == spec.sha256
        result.append((spec, ok))
    return result


def models_ready(folder: Path | None = None) -> bool:
    return all(ok for _spec, ok in model_status(folder))


def require_ocr_models() -> Path:
    folder = models_dir()
    if not models_ready(folder):
        raise RuntimeError(
            "OCR 모델이 없습니다. 배포본을 다시 설치하거나, "
            "개발 중이라면 ocr/models 에 공식 ONNX를 두세요."
        )
    return folder


def _download(spec: OcrModelSpec, dest: Path, progress: ProgressCallback | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if progress:
        progress(f"{spec.name} 받는 중 (~{spec.size_mb}MB)...")
    request = urllib.request.Request(
        spec.url,
        headers={"User-Agent": "TinyPDFEditor/1.1.8"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
        while True:
            chunk = response.read(1024 * 64)
            if not chunk:
                break
            out.write(chunk)
    digest = _file_sha256(tmp)
    if digest != spec.sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{spec.name} 해시가 맞지 않습니다. 다시 받아 주세요.")
    os.replace(tmp, dest)


def download_ocr_models(progress: ProgressCallback | None = None) -> Path:
    """Fetch official weights into the repo ocr/models folder (build / dev)."""
    folder = Path(__file__).resolve().parents[1] / "ocr" / "models"
    folder.mkdir(parents=True, exist_ok=True)
    for spec in ALL_OCR_MODELS:
        path = folder / spec.filename
        if path.is_file() and _file_sha256(path) == spec.sha256:
            continue
        _download(spec, path, progress)
    return folder
