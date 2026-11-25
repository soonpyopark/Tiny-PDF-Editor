/** 선택 도구용 잉크(펜·연필·형광펜) 클릭 판정·이동·크기 조절. */

import { MIN_BOX, clampDelta, handleCursor } from './shapeMath.js';

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function pointSegDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  if (lenSq <= 1e-12) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * dx + (py - ay) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function pointHitsStroke(stroke, strokeWidth, x, y, slack) {
  if (!Array.isArray(stroke) || !stroke.length) return false;
  const reach = Math.max(0, Number(strokeWidth) || 0) / 2 + Math.max(0, slack);
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const pt of stroke) {
    const px = Number(pt[0]);
    const py = Number(pt[1]);
    if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
    minX = Math.min(minX, px);
    minY = Math.min(minY, py);
    maxX = Math.max(maxX, px);
    maxY = Math.max(maxY, py);
  }
  if (!(minX <= maxX)) return false;
  if (x + reach < minX || maxX + reach < x || y + reach < minY || maxY + reach < y) return false;
  if (stroke.length === 1) {
    return Math.hypot(x - Number(stroke[0][0]), y - Number(stroke[0][1])) <= reach;
  }
  for (let i = 0; i < stroke.length - 1; i += 1) {
    const a = stroke[i];
    const b = stroke[i + 1];
    if (pointSegDist(x, y, Number(a[0]), Number(a[1]), Number(b[0]), Number(b[1])) <= reach) return true;
  }
  return false;
}

/**
 * 위에 있는 획부터 검사한다. 닿은 잉크를 돌려주거나 없으면 null.
 * @param {any[]} inks
 * @param {number} x
 * @param {number} y
 * @param {number} slack pt
 */
export function pickInk(inks, x, y, slack = 3) {
  const list = Array.isArray(inks) ? inks : [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const ink = list[i];
    const strokes = Array.isArray(ink?.strokes) ? ink.strokes : [];
    const width = Number(ink?.width) || 1;
    for (const stroke of strokes) {
      if (pointHitsStroke(stroke, width, x, y, slack)) return ink;
    }
  }
  return null;
}

/** 획 점만으로 잡은 상자(테두리 굵기 제외). */
export function inkBounds(ink) {
  const strokes = Array.isArray(ink?.strokes) ? ink.strokes : [];
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const stroke of strokes) {
    if (!Array.isArray(stroke)) continue;
    for (const pt of stroke) {
      const x = Number(pt[0]);
      const y = Number(pt[1]);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  if (!(minX <= maxX)) return [0, 0, 0, 0];
  return [minX, minY, maxX, maxY];
}

function mapStrokes(strokes, mapPoint) {
  return (Array.isArray(strokes) ? strokes : []).map((stroke) =>
    (Array.isArray(stroke) ? stroke : []).map((pt) => mapPoint(Number(pt[0]), Number(pt[1]))),
  );
}

function clampPointToPage(x, y, ptW, ptH) {
  return [clamp(x, 0, ptW), clamp(y, 0, ptH)];
}

/** 쪽 안에 머물게 옮긴 획. */
export function moveInk(ink, dx, dy, ptW, ptH) {
  const [mx, my] = clampDelta(inkBounds(ink), dx, dy, ptW, ptH);
  return {
    strokes: mapStrokes(ink.strokes, (x, y) => clampPointToPage(x + mx, y + my, ptW, ptH)),
  };
}

const RECT_HANDLES = [
  ['nw', 0, 0],
  ['n', 0.5, 0],
  ['ne', 1, 0],
  ['e', 1, 0.5],
  ['se', 1, 1],
  ['s', 0.5, 1],
  ['sw', 0, 1],
  ['w', 0, 0.5],
];

/** 선택 상자 8방향 손잡이. */
export function inkHandles(ink) {
  const [x0, y0, x1, y1] = inkBounds(ink);
  return RECT_HANDLES.map(([id, fx, fy]) => ({ id, x: x0 + (x1 - x0) * fx, y: y0 + (y1 - y0) * fy }));
}

export { handleCursor as inkHandleCursor };

/** 손잡이를 끌었을 때 획을 상자에 맞춰 늘리거나 줄인다. */
export function scaleInk(ink, handleId, x, y, ptW, ptH) {
  const px = clamp(x, 0, ptW);
  const py = clamp(y, 0, ptH);
  const [ox0, oy0, ox1, oy1] = inkBounds(ink);
  let x0 = ox0;
  let y0 = oy0;
  let x1 = ox1;
  let y1 = oy1;
  if (handleId.includes('w')) x0 = Math.min(px, x1 - MIN_BOX);
  if (handleId.includes('e')) x1 = Math.max(px, x0 + MIN_BOX);
  if (handleId.includes('n')) y0 = Math.min(py, y1 - MIN_BOX);
  if (handleId.includes('s')) y1 = Math.max(py, y0 + MIN_BOX);
  const oldW = ox1 - ox0;
  const oldH = oy1 - oy0;
  const sx = Math.abs(oldW) < 1e-6 ? 1 : (x1 - x0) / oldW;
  const sy = Math.abs(oldH) < 1e-6 ? 1 : (y1 - y0) / oldH;
  return {
    strokes: mapStrokes(ink.strokes, (ptX, ptY) =>
      clampPointToPage(x0 + (ptX - ox0) * sx, y0 + (ptY - oy0) * sy, ptW, ptH),
    ),
  };
}

export function sameInkStrokes(a, b, eps = 0.05) {
  const as = Array.isArray(a) ? a : [];
  const bs = Array.isArray(b) ? b : [];
  if (as.length !== bs.length) return false;
  return as.every((stroke, i) => {
    const other = bs[i];
    if (!Array.isArray(stroke) || !Array.isArray(other) || stroke.length !== other.length) return false;
    return stroke.every(
      (pt, j) => Math.abs(Number(pt[0]) - Number(other[j][0])) <= eps && Math.abs(Number(pt[1]) - Number(other[j][1])) <= eps,
    );
  });
}

export function withInkStrokes(ink, strokes) {
  const next = { ...ink, strokes };
  const [x0, y0, x1, y1] = inkBounds(next);
  const pad = Math.max(0.5, (Number(ink.width) || 0) / 2);
  next.rect = [x0 - pad, y0 - pad, x1 + pad, y1 + pad];
  return next;
}
