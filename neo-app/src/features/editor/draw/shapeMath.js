// 도형 좌표 계산(순수 함수). 좌표는 모두 쪽 화면 좌표(pt, 회전 반영)다.
//
// 도형 모양(geom): 점으로 그리는 도형은 { points: [[x, y], …] }, 상자로 그리는 도형은 { rect: [x0, y0, x1, y1] }.
// 도형(shape): { id, pageIndex, kind, params, ...geom }

import { isPointKind } from './shapeSettings.js';

export const MIN_BOX = 4;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function geomOf(shape) {
  return isPointKind(shape.kind) ? { points: shape.points.map((p) => [p[0], p[1]]) } : { rect: [...shape.rect] };
}

export function withGeom(shape, geom) {
  const next = { ...shape };
  delete next.points;
  delete next.rect;
  return { ...next, ...geom };
}

/** 도형이 차지하는 상자 [x0, y0, x1, y1] (테두리 굵기 제외). */
export function shapeBounds(shape) {
  if (shape.points) {
    const xs = shape.points.map((p) => p[0]);
    const ys = shape.points.map((p) => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }
  return [...shape.rect];
}

/** 두 점을 대각선으로 하는 상자. square 이면 정사각형(긴 쪽 기준)으로 맞춘다. */
export function rectFromDrag(a, b, square = false) {
  let dx = b.x - a.x;
  let dy = b.y - a.y;
  if (square) {
    const size = Math.max(Math.abs(dx), Math.abs(dy));
    dx = Math.sign(dx || 1) * size;
    dy = Math.sign(dy || 1) * size;
  }
  const x1 = a.x + dx;
  const y1 = a.y + dy;
  return [Math.min(a.x, x1), Math.min(a.y, y1), Math.max(a.x, x1), Math.max(a.y, y1)];
}

/** Shift 를 누르고 그릴 때 시작점에서 45° 단위 각도로 맞춘 끝점. */
export function snapAngle(start, point) {
  const dx = point.x - start.x;
  const dy = point.y - start.y;
  const length = Math.hypot(dx, dy);
  if (length < 0.01) return point;
  const step = Math.PI / 4;
  const angle = Math.round(Math.atan2(dy, dx) / step) * step;
  return { x: start.x + Math.cos(angle) * length, y: start.y + Math.sin(angle) * length };
}

export function clampPoint(point, ptW, ptH) {
  return { x: clamp(point.x, 0, ptW), y: clamp(point.y, 0, ptH) };
}

// --------------------------------------------------------------------------- 클릭 판정

export function distToSegment(px, py, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSq = dx * dx + dy * dy;
  const t = lengthSq === 0 ? 0 : clamp(((px - a[0]) * dx + (py - a[1]) * dy) / lengthSq, 0, 1);
  return Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy));
}

export function polygonContains(points, x, y) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function nearEdges(points, closed, x, y, reach) {
  const count = closed ? points.length : points.length - 1;
  for (let i = 0; i < count; i += 1) {
    if (distToSegment(x, y, points[i], points[(i + 1) % points.length]) <= reach) return true;
  }
  return false;
}

/** 이 도형이 (x, y) 에 걸리는가. tol 은 여유(pt). 속이 빈 도형은 선 가까이만, 색이 채워진 도형·텍스트 상자는 안쪽도 걸린다. */
export function hitShape(shape, x, y, tol) {
  const half = Math.max(0, shape.params?.width ?? 0) / 2;
  const reach = tol + half;
  const filled = Boolean(shape.params?.fill);
  const { kind } = shape;
  if (kind === 'line' || kind === 'arrow' || kind === 'polyline') {
    return nearEdges(shape.points, false, x, y, reach + (kind === 'arrow' ? 3 : 0));
  }
  if (kind === 'polygon' || kind === 'cloud') {
    return (filled && polygonContains(shape.points, x, y)) || nearEdges(shape.points, true, x, y, reach);
  }
  const [x0, y0, x1, y1] = shape.rect;
  if (kind === 'text') {
    return x >= x0 - reach && x <= x1 + reach && y >= y0 - reach && y <= y1 + reach;
  }
  if (kind === 'ellipse') {
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const a = Math.max(0.5, (x1 - x0) / 2);
    const b = Math.max(0.5, (y1 - y0) / 2);
    const r = Math.hypot((x - cx) / a, (y - cy) / b);
    if (filled && r <= 1) return true;
    return Math.abs(r - 1) * Math.min(a, b) <= reach;
  }
  // rect
  const inOuter = x >= x0 - reach && x <= x1 + reach && y >= y0 - reach && y <= y1 + reach;
  if (!inOuter) return false;
  if (filled) return true;
  const inInner = x > x0 + reach && x < x1 - reach && y > y0 + reach && y < y1 - reach;
  return !inInner;
}

/** 겹쳐 있으면 나중에 그린(위에 있는) 도형을 고른다. */
export function pickShape(shapes, x, y, tol) {
  for (let i = shapes.length - 1; i >= 0; i -= 1) {
    if (hitShape(shapes[i], x, y, tol)) return shapes[i];
  }
  return null;
}

// --------------------------------------------------------------------------- 이동·크기 조절

/** 쪽 밖으로 나가지 않게 이동량을 줄인다. (도형이 쪽보다 크면 그대로 둔다.) */
export function clampDelta(bounds, dx, dy, ptW, ptH) {
  const [x0, y0, x1, y1] = bounds;
  const lowX = -x0;
  const highX = ptW - x1;
  const lowY = -y0;
  const highY = ptH - y1;
  return [lowX <= highX ? clamp(dx, lowX, highX) : dx, lowY <= highY ? clamp(dy, lowY, highY) : dy];
}

export function moveGeom(shape, dx, dy, ptW, ptH) {
  const [mx, my] = clampDelta(shapeBounds(shape), dx, dy, ptW, ptH);
  if (shape.points) return { points: shape.points.map(([x, y]) => [x + mx, y + my]) };
  const [x0, y0, x1, y1] = shape.rect;
  return { rect: [x0 + mx, y0 + my, x1 + mx, y1 + my] };
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

/** 선택했을 때 보이는 손잡이. 상자 도형은 8방향, 점 도형은 꼭짓점마다 하나. */
export function shapeHandles(shape) {
  if (shape.points) return shape.points.map(([x, y], i) => ({ id: `p${i}`, x, y }));
  const [x0, y0, x1, y1] = shape.rect;
  return RECT_HANDLES.map(([id, fx, fy]) => ({ id, x: x0 + (x1 - x0) * fx, y: y0 + (y1 - y0) * fy }));
}

export function handleCursor(id) {
  if (id.startsWith('p')) return 'crosshair';
  if (id === 'n' || id === 's') return 'ns-resize';
  if (id === 'e' || id === 'w') return 'ew-resize';
  return id === 'nw' || id === 'se' ? 'nwse-resize' : 'nesw-resize';
}

/** 손잡이를 (x, y) 로 끌었을 때의 새 모양. */
export function dragHandle(shape, handleId, x, y, ptW, ptH) {
  const px = clamp(x, 0, ptW);
  const py = clamp(y, 0, ptH);
  if (shape.points) {
    const index = Number(handleId.slice(1));
    return { points: shape.points.map((p, i) => (i === index ? [px, py] : [p[0], p[1]])) };
  }
  let [x0, y0, x1, y1] = shape.rect;
  if (handleId.includes('w')) x0 = Math.min(px, x1 - MIN_BOX);
  if (handleId.includes('e')) x1 = Math.max(px, x0 + MIN_BOX);
  if (handleId.includes('n')) y0 = Math.min(py, y1 - MIN_BOX);
  if (handleId.includes('s')) y1 = Math.max(py, y0 + MIN_BOX);
  return { rect: [x0, y0, x1, y1] };
}

export function sameGeom(a, b, eps = 0.01) {
  if (a.rect && b.rect) return a.rect.every((v, i) => Math.abs(v - b.rect[i]) <= eps);
  if (!a.points || !b.points || a.points.length !== b.points.length) return false;
  return a.points.every((p, i) => Math.abs(p[0] - b.points[i][0]) <= eps && Math.abs(p[1] - b.points[i][1]) <= eps);
}

/** 그리는 중 미리보기 도형(엔진에 아직 없는 것). 모양은 도구 막대 설정을 엔진 모양으로 바꾼 params 를 쓴다. */
export function draftShape(kind, geom, params) {
  return { id: null, pageIndex: -1, kind, params, ...geom };
}
