// 이미지 넣기 상자의 이동·크기 계산 (순수 함수). 좌표는 모두 PDF 쪽 화면 좌표(pt).
// rect = [x0, y0, x1, y1], page = [x0, y0, width, height].
//
// 원칙(WYSIWYG): 화면에 그려지는 상자 = 여기서 계산한 rect = PDF 에 확정되는 rect.
// 화면용 최소 크기 같은 보정을 따로 두지 않는다. 최소 크기는 여기서 비율을 지키며 정한다.

/** 짧은 변의 최소 길이(pt). 이보다 작게는 줄이지 않는다(핸들을 잡을 수 없게 되므로). */
export const MIN_SIDE = 16;

export const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

export function imageAspect(width, height) {
  const w = Number(width);
  const h = Number(height);
  if (!(w > 0) || !(h > 0)) return 1;
  return w / h;
}

/** 비율을 지킨 최소 가로. 짧은 변이 MIN_SIDE 가 되게 한다. */
export function minWidthFor(aspect) {
  return aspect >= 1 ? MIN_SIDE * aspect : MIN_SIDE;
}

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

/** 상자가 쪽 밖으로 나가지 않게 옮긴다 (크기는 그대로). 쪽보다 크면 쪽에 맞춰 줄인다. */
export function clampRectToPage(rect, page) {
  const [px0, py0, pw, ph] = page;
  let width = Math.max(1, rect[2] - rect[0]);
  let height = Math.max(1, rect[3] - rect[1]);
  if (width > pw || height > ph) {
    const scale = Math.min(pw / width, ph / height);
    width *= scale;
    height *= scale;
  }
  const x0 = clamp(rect[0], px0, px0 + pw - width);
  const y0 = clamp(rect[1], py0, py0 + ph - height);
  return [x0, y0, x0 + width, y0 + height];
}

export function moveRect(origin, dx, dy, page) {
  return clampRectToPage([origin[0] + dx, origin[1] + dy, origin[2] + dx, origin[3] + dy], page);
}

/** 핸들이 있는 점 (잡은 자리와 핸들 중심의 차이를 구할 때 쓴다). */
export function handlePoint(rect, handle) {
  const [x0, y0, x1, y1] = rect;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const map = {
    nw: [x0, y0],
    n: [cx, y0],
    ne: [x1, y0],
    e: [x1, cy],
    se: [x1, y1],
    s: [cx, y1],
    sw: [x0, y1],
    w: [x0, cy],
  };
  return map[handle];
}

/**
 * 모서리: 반대쪽 모서리를 고정하고, 커서가 가리키는 만큼 비율을 지키며 키운다.
 * - 커서가 고정점을 넘어가도 뒤집히지 않는다(최소 크기에서 멈춤).
 * - 쪽 경계에서는 상자를 밀지 않고 거기서 멈춘다(고정 모서리는 움직이지 않음).
 */
function resizeFromCorner(origin, handle, point, aspect, page) {
  const [px0, py0, pw, ph] = page;
  const [x0, y0, x1, y1] = origin;
  const east = handle === 'ne' || handle === 'se'; // 오른쪽으로 자란다
  const south = handle === 'sw' || handle === 'se'; // 아래로 자란다
  const fixedX = east ? x0 : x1;
  const fixedY = south ? y0 : y1;
  const dx = east ? point.x - fixedX : fixedX - point.x;
  const dy = south ? point.y - fixedY : fixedY - point.y;
  const availW = east ? px0 + pw - fixedX : fixedX - px0;
  const availH = south ? py0 + ph - fixedY : fixedY - py0;
  const minW = minWidthFor(aspect);
  const maxW = Math.max(minW, Math.min(availW, availH * aspect));
  const width = clamp(Math.max(dx, dy * aspect), minW, maxW);
  const height = width / aspect;
  const nx0 = east ? fixedX : fixedX - width;
  const nx1 = east ? fixedX + width : fixedX;
  const ny0 = south ? fixedY : fixedY - height;
  const ny1 = south ? fixedY + height : fixedY;
  return [nx0, ny0, nx1, ny1];
}

/** 변: 반대쪽 변을 고정하고 그 축 길이로 크기를 정한다. 비율은 유지하고 다른 축은 가운데를 지킨다. */
function resizeFromEdge(origin, handle, point, aspect, page) {
  const [px0, py0, pw, ph] = page;
  const [x0, y0, x1, y1] = origin;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const minW = minWidthFor(aspect);
  if (handle === 'e' || handle === 'w') {
    const raw = handle === 'e' ? point.x - x0 : x1 - point.x;
    const avail = handle === 'e' ? px0 + pw - x0 : x1 - px0;
    const crossMax = 2 * Math.min(cy - py0, py0 + ph - cy) * aspect; // 위아래로 쪽을 벗어나지 않게
    const width = clamp(raw, minW, Math.max(minW, Math.min(avail, crossMax)));
    const height = width / aspect;
    return handle === 'e'
      ? [x0, cy - height / 2, x0 + width, cy + height / 2]
      : [x1 - width, cy - height / 2, x1, cy + height / 2];
  }
  const minH = minW / aspect;
  const raw = handle === 's' ? point.y - y0 : y1 - point.y;
  const avail = handle === 's' ? py0 + ph - y0 : y1 - py0;
  const crossMax = (2 * Math.min(cx - px0, px0 + pw - cx)) / aspect;
  const height = clamp(raw, minH, Math.max(minH, Math.min(avail, crossMax)));
  const width = height * aspect;
  return handle === 's'
    ? [cx - width / 2, y0, cx + width / 2, y0 + height]
    : [cx - width / 2, y1 - height, cx + width / 2, y1];
}

/**
 * handle 을 point 로 끌었을 때의 새 rect.
 * grab 은 잡은 순간 커서와 핸들 중심의 차이(선택) — 있으면 핸들이 커서 밑에 그대로 붙어 따라온다.
 */
export function resizeRect(origin, handle, point, aspect, page, grab = null) {
  const target = grab ? { x: point.x - grab.x, y: point.y - grab.y } : point;
  if (handle === 'nw' || handle === 'ne' || handle === 'se' || handle === 'sw') {
    return resizeFromCorner(origin, handle, target, aspect, page);
  }
  return resizeFromEdge(origin, handle, target, aspect, page);
}

/** rect 를 쪽 안의 퍼센트 위치/크기로. 화면용 보정 없이 그대로 쓴다. */
export function styleFromRect(rect, page) {
  const [px0, py0, pw, ph] = page;
  return {
    left: `${((rect[0] - px0) / pw) * 100}%`,
    top: `${((rect[1] - py0) / ph) * 100}%`,
    width: `${((rect[2] - rect[0]) / pw) * 100}%`,
    height: `${((rect[3] - rect[1]) / ph) * 100}%`,
  };
}
