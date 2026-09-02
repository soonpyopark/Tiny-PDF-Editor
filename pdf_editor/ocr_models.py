"""Official Paddle PP-OCRv5 ONNX weights bundled with the app."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OcrModelSpec:
    name: str
    filename: str
    sha256: str


OCR_DET_MODEL = OcrModelSpec(
    name="PP-OCRv5 mobile det",
    filename="det.onnx",
    sha256="a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d",
)
OCR_REC_MODEL = OcrModelSpec(
    name="PP-OCRv5 korean rec",
    filename="rec_korean.onnx",
    sha256="92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08",
)
OCR_REC_DICT = OcrModelSpec(
    name="PP-OCRv5 korean dict",
    filename="rec_korean.yml",
    sha256="f757fa1c40e99edcf27e9cce879b93eb2a51fa46f5ef39095689b8c37dd75998",
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
