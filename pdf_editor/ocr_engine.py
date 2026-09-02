"""PP-OCRv5 mobile det + korean rec via onnxruntime (no Paddle / OpenCV)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from pdf_editor.ocr_models import OCR_DET_MODEL, OCR_REC_DICT, OCR_REC_MODEL, require_ocr_models

DET_LONG_SIDE = 960
DET_THRESH = 0.3
DET_BOX_THRESH = 0.6
DET_UNCLIP_RATIO = 1.5
DET_MIN_SIZE = 3
DET_MAX_BOXES = 1000
REC_HEIGHT = 48
REC_MIN_WIDTH = 320
REC_MAX_WIDTH = 3200
TEXT_SCORE = 0.5
DET_MEAN = (0.485, 0.456, 0.406)
DET_STD = (0.229, 0.224, 0.225)
IOU_THRESH = 0.45


@dataclass(frozen=True)
class OcrLine:
    text: str
    x: float
    y: float
    w: float
    h: float
    conf: float


def parse_character_dict(yml: str) -> list[str]:
    chars: list[str] = []
    in_dict = False
    dict_indent = -1
    for line in yml.splitlines():
        if not in_dict:
            stripped = line.lstrip()
            if stripped.startswith("character_dict:"):
                in_dict = True
                dict_indent = len(line) - len(stripped)
            continue
        match_indent = len(line) - len(line.lstrip(" "))
        body = line.lstrip()
        if body.startswith("- ") and match_indent >= dict_indent:
            value = body[2:]
            if len(value) >= 2 and (
                (value.startswith("'") and value.endswith("'"))
                or (value.startswith('"') and value.endswith('"'))
            ):
                value = value[1:-1].replace("''", "'")
            chars.append(value)
            continue
        if line.strip():
            break
    return chars


def _resize_rgb(image: np.ndarray, width: int, height: int) -> np.ndarray:
    pil = Image.fromarray(image, mode="RGB")
    return np.asarray(pil.resize((width, height), Image.Resampling.BILINEAR), dtype=np.uint8)


def _ctc_decode(data: np.ndarray, dictionary: list[str]) -> tuple[str, float] | None:
    time_steps, classes = data.shape
    text = ""
    conf_sum = 0.0
    conf_count = 0
    prev = -1
    for step in range(time_steps):
        row = data[step]
        best = int(np.argmax(row))
        best_v = float(row[best])
        repeat = best == prev
        prev = best
        if best == 0 or repeat:
            continue
        prob = best_v
        if prob > 1.0001 or prob < 0:
            shifted = row - best_v
            denom = float(np.exp(shifted).sum())
            prob = 1.0 / denom if denom else 0.0
        conf_sum += prob
        conf_count += 1
        if 1 <= best <= len(dictionary):
            text += dictionary[best - 1]
        elif best == len(dictionary) + 1:
            text += " "
    if not text:
        return None
    return text, (conf_sum / conf_count if conf_count else 0.0)


def _component_boxes(prob: np.ndarray, width: int, height: int) -> list[tuple[int, int, int, int, float]]:
    visited = np.zeros(width * height, dtype=np.uint8)
    boxes: list[tuple[int, int, int, int, float]] = []
    flat = np.asarray(prob, dtype=np.float32).reshape(-1)
    for start in range(width * height):
        if visited[start] or flat[start] <= DET_THRESH:
            continue
        x1 = start % width
        x2 = x1
        y1 = start // width
        y2 = y1
        total = 0.0
        count = 0
        stack = [start]
        visited[start] = 1
        while stack:
            pos = stack.pop()
            px = pos % width
            py = pos // width
            total += float(flat[pos])
            count += 1
            if px < x1:
                x1 = px
            if px > x2:
                x2 = px
            if py < y1:
                y1 = py
            if py > y2:
                y2 = py
            neighbors = []
            if px > 0:
                neighbors.append(pos - 1)
            if px < width - 1:
                neighbors.append(pos + 1)
            if py > 0:
                neighbors.append(pos - width)
            if py < height - 1:
                neighbors.append(pos + width)
            for nxt in neighbors:
                if not visited[nxt] and flat[nxt] > DET_THRESH:
                    visited[nxt] = 1
                    stack.append(nxt)
        if (x2 - x1 + 1) < DET_MIN_SIZE and (y2 - y1 + 1) < DET_MIN_SIZE:
            continue
        boxes.append((x1, y1, x2, y2, total / max(count, 1)))
    boxes = [box for box in boxes if box[4] >= DET_BOX_THRESH]
    boxes.sort(key=lambda item: (item[1], item[0]))
    return boxes


def _iou(a: OcrLine, b: OcrLine) -> float:
    ax2, ay2 = a.x + a.w, a.y + a.h
    bx2, by2 = b.x + b.w, b.y + b.h
    ix1 = max(a.x, b.x)
    iy1 = max(a.y, b.y)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


def _y_overlap_ratio(a: OcrLine, b: OcrLine) -> float:
    top = max(a.y, b.y)
    bottom = min(a.y + a.h, b.y + b.h)
    overlap = max(0.0, bottom - top)
    return overlap / max(min(a.h, b.h), 1.0)


def dedup_lines(items: list[OcrLine]) -> list[OcrLine]:
    ranked = sorted(items, key=lambda item: item.conf, reverse=True)
    kept: list[OcrLine] = []
    for item in ranked:
        duplicate = False
        for other in kept:
            if _iou(item, other) >= IOU_THRESH:
                duplicate = True
                break
            if item.text.strip() == other.text.strip() and _y_overlap_ratio(item, other) >= 0.6:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    kept.sort(key=lambda item: (item.y, item.x))
    return kept


class OcrEngine:
    def __init__(self, models: Path) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.log_severity_level = 3
        self._det = ort.InferenceSession(
            str(models / OCR_DET_MODEL.filename),
            options,
            providers=["CPUExecutionProvider"],
        )
        self._rec = ort.InferenceSession(
            str(models / OCR_REC_MODEL.filename),
            options,
            providers=["CPUExecutionProvider"],
        )
        yaml_text = (models / OCR_REC_DICT.filename).read_text(encoding="utf-8")
        self._dict = parse_character_dict(yaml_text)
        if not self._dict:
            raise RuntimeError("OCR 한글 사전을 읽지 못했습니다. 모델을 다시 받아 주세요.")

    def recognize_page(self, rgb: np.ndarray) -> list[OcrLine]:
        height, width = rgb.shape[:2]
        if width < DET_MIN_SIZE or height < DET_MIN_SIZE:
            return []
        boxes = self._detect(rgb)
        items: list[OcrLine] = []
        for x, y, w, h in boxes:
            line = self._recognize_line(rgb, x, y, w, h)
            if line is None or not line.text.strip():
                continue
            if line.conf >= TEXT_SCORE:
                items.append(line)
        return dedup_lines(items)

    def _detect(self, rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
        height, width = rgb.shape[:2]
        ratio = DET_LONG_SIDE / max(width, height)
        det_w = max(32, int(round(width * ratio / 32)) * 32)
        det_h = max(32, int(round(height * ratio / 32)) * 32)
        resized = _resize_rgb(rgb, det_w, det_h)
        bgr = resized.astype(np.float32) / 255.0
        channels = [
            (bgr[:, :, 2] - DET_MEAN[0]) / DET_STD[0],
            (bgr[:, :, 1] - DET_MEAN[1]) / DET_STD[1],
            (bgr[:, :, 0] - DET_MEAN[2]) / DET_STD[2],
        ]
        tensor = np.stack(channels, axis=0).reshape(1, 3, det_h, det_w)
        inp_name = self._det.get_inputs()[0].name
        out_name = self._det.get_outputs()[0].name
        prob = self._det.run([out_name], {inp_name: tensor})[0]
        raw = _component_boxes(prob, det_w, det_h)
        sx = width / det_w
        sy = height / det_h
        boxes: list[tuple[int, int, int, int]] = []
        for x1, y1, x2, y2, _score in raw[:DET_MAX_BOXES]:
            bw = x2 - x1 + 1
            bh = y2 - y1 + 1
            delta = bw * bh * DET_UNCLIP_RATIO / (2 * (bw + bh))
            px1 = max(0, int((x1 - delta) * sx))
            py1 = max(0, int((y1 - delta) * sy))
            px2 = min(width, int(np.ceil((x2 + 1 + delta) * sx)))
            py2 = min(height, int(np.ceil((y2 + 1 + delta) * sy)))
            if px2 - px1 < DET_MIN_SIZE or py2 - py1 < DET_MIN_SIZE:
                continue
            boxes.append((px1, py1, px2 - px1, py2 - py1))
        return boxes

    def _recognize_line(
        self,
        rgb: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> OcrLine | None:
        crop = rgb[y : y + h, x : x + w]
        if crop.size == 0:
            return None
        rec_w = min(REC_MAX_WIDTH, max(16, int(round(w * REC_HEIGHT / max(h, 1)))))
        padded = max(REC_MIN_WIDTH, rec_w)
        resized = _resize_rgb(crop, rec_w, REC_HEIGHT)
        tensor = np.zeros((1, 3, REC_HEIGHT, padded), dtype=np.float32)
        scaled = resized.astype(np.float32) / 255.0 / 0.5 - 1.0
        tensor[0, 0, :, :rec_w] = scaled[:, :, 2]
        tensor[0, 1, :, :rec_w] = scaled[:, :, 1]
        tensor[0, 2, :, :rec_w] = scaled[:, :, 0]
        inp_name = self._rec.get_inputs()[0].name
        out_name = self._rec.get_outputs()[0].name
        logits = self._rec.run([out_name], {inp_name: tensor})[0]
        decoded = _ctc_decode(np.asarray(logits[0]), self._dict)
        if decoded is None:
            return None
        text, conf = decoded
        return OcrLine(text=text, x=float(x), y=float(y), w=float(w), h=float(h), conf=conf)


@lru_cache(maxsize=1)
def _cached_engine(models_path: str) -> OcrEngine:
    return OcrEngine(Path(models_path))


def get_ocr_engine() -> OcrEngine:
    folder = require_ocr_models()
    return _cached_engine(str(folder.resolve()))


def reset_ocr_engine() -> None:
    _cached_engine.cache_clear()
