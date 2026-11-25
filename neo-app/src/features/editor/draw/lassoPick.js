/** 올가미 경로에 닿거나, 닫힌 올가미 안에 있는 잉크·도형을 고른다. */

import { distToSegment, polygonContains, shapeBounds } from './shapeMath.js';
import { inkBounds } from './inkPick.js';

function segmentsIntersect(a0, a1, b0, b1) {
  const ax = a1[0] - a0[0];
  const ay = a1[1] - a0[1];
  const bx = b1[0] - b0[0];
  const by = b1[1] - b0[1];
  const den = ax * by - ay * bx;
  if (Math.abs(den) < 1e-12) {
    // 거의 평행: 끝점이 다른 선분에 가까이 있으면 닿은 것으로 본다.
    return (
      distToSegment(a0[0], a0[1], b0, b1) <= 0.5 ||
      distToSegment(a1[0], a1[1], b0, b1) <= 0.5 ||
      distToSegment(b0[0], b0[1], a0, a1) <= 0.5 ||
      distToSegment(b1[0], b1[1], a0, a1) <= 0.5
    );
  }
  const t = ((b0[0] - a0[0]) * by - (b0[1] - a0[1]) * bx) / den;
  const u = ((b0[0] - a0[0]) * ay - (b0[1] - a0[1]) * ax) / den;
  return t >= -1e-6 && t <= 1 + 1e-6 && u >= -1e-6 && u <= 1 + 1e-6;
}

function polylineSegments(points, closed) {
  const list = [];
  if (!Array.isArray(points) || points.length < 2) return list;
  const n = closed ? points.length : points.length - 1;
  for (let i = 0; i < n; i += 1) {
    list.push([points[i], points[(i + 1) % points.length]]);
  }
  return list;
}

/** 두 폴리라인이 reach 안에서 닿거나 교차하면 true. */
export function polylinesTouch(a, aClosed, b, bClosed, reach = 3) {
  const aPts = Array.isArray(a) ? a : [];
  const bPts = Array.isArray(b) ? b : [];
  if (!aPts.length || !bPts.length) return false;
  const r = Math.max(0, reach);
  for (const p of aPts) {
    for (const [b0, b1] of polylineSegments(bPts, bClosed)) {
      if (distToSegment(p[0], p[1], b0, b1) <= r) return true;
    }
  }
  for (const p of bPts) {
    for (const [a0, a1] of polylineSegments(aPts, aClosed)) {
      if (distToSegment(p[0], p[1], a0, a1) <= r) return true;
    }
  }
  for (const [a0, a1] of polylineSegments(aPts, aClosed)) {
    for (const [b0, b1] of polylineSegments(bPts, bClosed)) {
      if (segmentsIntersect(a0, a1, b0, b1)) return true;
    }
  }
  return false;
}

function pointsInsidePolygon(points, polygon) {
  if (!Array.isArray(points) || polygon.length < 3) return false;
  return points.some((p) => polygonContains(polygon, p[0], p[1]));
}

/**
 * 올가미 경로에 획이 닿거나, 닫힌 올가미 안에 점이 있으면 선택.
 * @param {any} ink
 * @param {number[][]} lasso
 * @param {number} reach pt
 */
export function inkHitsLasso(ink, lasso, reach = 3) {
  const path = Array.isArray(lasso) ? lasso : [];
  if (path.length < 2) return false;
  const closed = path.length >= 3;
  const pad = Math.max(0, Number(ink?.width) || 0) / 2 + reach;
  const strokes = Array.isArray(ink?.strokes) ? ink.strokes : [];
  for (const stroke of strokes) {
    if (!Array.isArray(stroke) || !stroke.length) continue;
    if (polylinesTouch(stroke, false, path, false, pad)) return true;
    if (closed && pointsInsidePolygon(stroke, path)) return true;
  }
  return false;
}

function shapeOutline(shape) {
  if (Array.isArray(shape?.points) && shape.points.length) {
    return {
      points: shape.points,
      closed: shape.kind === 'polygon' || shape.kind === 'cloud',
    };
  }
  if (!Array.isArray(shape?.rect) || shape.rect.length !== 4) return { points: [], closed: false };
  const [x0, y0, x1, y1] = shape.rect;
  if (shape.kind === 'ellipse') {
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const rx = Math.max(0.5, (x1 - x0) / 2);
    const ry = Math.max(0.5, (y1 - y0) / 2);
    const pts = [];
    for (let i = 0; i < 24; i += 1) {
      const a = (i / 24) * Math.PI * 2;
      pts.push([cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]);
    }
    return { points: pts, closed: true };
  }
  return {
    points: [
      [x0, y0],
      [x1, y0],
      [x1, y1],
      [x0, y1],
    ],
    closed: true,
  };
}

/**
 * 올가미 경로에 도형 윤곽이 닿거나, 닫힌 올가미 안에 들어가면 선택.
 * @param {any} shape
 * @param {number[][]} lasso
 * @param {number} reach pt
 */
export function shapeHitsLasso(shape, lasso, reach = 3) {
  const path = Array.isArray(lasso) ? lasso : [];
  if (path.length < 2) return false;
  const closed = path.length >= 3;
  const pad = Math.max(0, Number(shape?.params?.width) || 0) / 2 + reach;
  const outline = shapeOutline(shape);
  if (!outline.points.length) return false;
  if (polylinesTouch(outline.points, outline.closed, path, false, pad)) return true;
  if (closed && pointsInsidePolygon(outline.points, path)) return true;
  // 올가미가 채워진 도형·텍스트 상자 안을 지나가면 선택
  if (closed || path.length >= 2) {
    const sample = path;
    for (const p of sample) {
      if (shape.kind === 'text' || shape.params?.fill) {
        const [x0, y0, x1, y1] = shapeBounds(shape);
        if (p[0] >= x0 && p[0] <= x1 && p[1] >= y0 && p[1] <= y1) return true;
      }
    }
  }
  return false;
}

/**
 * 올가미에 걸린 항목 목록. 잉크·도형 모두, 위에 그려진 순서 유지.
 * @returns {{ pageIndex: number, id: number, kind: 'ink'|'shape' }[]}
 */
export function pickLassoHits(inks, shapes, pageIndex, lasso, reach = 3) {
  const hits = [];
  for (const ink of Array.isArray(inks) ? inks : []) {
    if (inkHitsLasso(ink, lasso, reach)) hits.push({ pageIndex, id: ink.id, kind: 'ink' });
  }
  for (const shape of Array.isArray(shapes) ? shapes : []) {
    if (shapeHitsLasso(shape, lasso, reach)) hits.push({ pageIndex, id: shape.id, kind: 'shape' });
  }
  return hits;
}

/** 선택 항목들의 합친 상자. */
export function selectionBounds(items, inks, shapes) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const item of items || []) {
    if (item.kind === 'ink') {
      const ink = (inks || []).find((entry) => entry.id === item.id);
      if (!ink) continue;
      const [x0, y0, x1, y1] = inkBounds(ink);
      minX = Math.min(minX, x0);
      minY = Math.min(minY, y0);
      maxX = Math.max(maxX, x1);
      maxY = Math.max(maxY, y1);
    } else {
      const shape = (shapes || []).find((entry) => entry.id === item.id);
      if (!shape) continue;
      const [x0, y0, x1, y1] = shapeBounds(shape);
      minX = Math.min(minX, x0);
      minY = Math.min(minY, y0);
      maxX = Math.max(maxX, x1);
      maxY = Math.max(maxY, y1);
    }
  }
  if (!(minX <= maxX)) return null;
  return [minX, minY, maxX, maxY];
}
