/** 선택 도구용 잉크(펜·연필·형광펜) 클릭 판정. */

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
