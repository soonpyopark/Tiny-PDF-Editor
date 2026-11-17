// 이미지 편집(이미 넣은 그림 다루기)용 순수 계산. 좌표는 PDF 쪽 화면 좌표(pt).
// rect = [x0, y0, x1, y1], page = [x0, y0, width, height].
import { MIN_SIDE, clampRectToPage, moveRect } from './imageBoxMath.js';

const PT_PER_MM = 72 / 25.4;
/** 원본 그림 1px 을 몇 pt 로 볼지(96dpi 기준). */
const PT_PER_PX = 0.75;

export const mmFromPt = (pt) => pt / PT_PER_MM;
export const ptFromMm = (mm) => mm * PT_PER_MM;

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

export function rectSize(rect) {
  return { width: rect[2] - rect[0], height: rect[3] - rect[1] };
}

/** 회전을 반영한 원본 크기(자르기 전). */
export function transformedSize(params) {
  const ow = Math.max(1, Number(params.ow) || 1);
  const oh = Math.max(1, Number(params.oh) || 1);
  return params.rot === 90 || params.rot === 270 ? { width: oh, height: ow } : { width: ow, height: oh };
}

export function normalizeCrop(raw, maxTotal = 0.95) {
  let [l, t, r, b] = Array.isArray(raw) && raw.length === 4 ? raw.map((v) => clamp(Number(v) || 0, 0, maxTotal)) : [0, 0, 0, 0];
  if (l + r > maxTotal) {
    const k = maxTotal / (l + r);
    l *= k;
    r *= k;
  }
  if (t + b > maxTotal) {
    const k = maxTotal / (t + b);
    t *= k;
    b *= k;
  }
  return [l, t, r, b];
}

/** 자르기까지 반영한, 보이는 그림의 가로/세로 비 (엔진 natural_aspect 와 같다). */
export function visibleAspect(params) {
  const { width, height } = transformedSize(params);
  const [l, t, r, b] = normalizeCrop(params.crop);
  return (width * (1 - l - r)) / Math.max(1e-6, height * (1 - t - b));
}

/** 엔진을 거치지 않아도 되는 변경(투명도·자르기·잠금)을 바로 적용한다. */
export function applyLocalPatch(params, patch) {
  const next = { ...params };
  if ('op' in patch) next.op = clamp(Math.round(Number(patch.op) || 100), 5, 100);
  if ('lock' in patch) next.lock = Boolean(patch.lock);
  if (patch.cropReset) next.crop = [0, 0, 0, 0];
  if ('crop' in patch) next.crop = normalizeCrop(patch.crop);
  return next;
}

/** 엔진 왕복이 필요한 변경인가? (미리보기 그림이 달라지는 것) */
export function needsEngine(patch) {
  return Boolean(patch.bg || patch.adj || patch.rotate || patch.flip);
}

/** 자르기가 바뀌어도 그림 크기(배율)는 그대로 두고, 보이는 영역만 달라지게 한 새 rect. */
export function rectAfterCrop(rect, oldCrop, newCrop, page) {
  const [l0, t0, r0, b0] = normalizeCrop(oldCrop);
  const [l, t, r, b] = normalizeCrop(newCrop);
  const { width, height } = rectSize(rect);
  const fullW = width / Math.max(1e-6, 1 - l0 - r0);
  const fullH = height / Math.max(1e-6, 1 - t0 - b0);
  const originX = rect[0] - l0 * fullW;
  const originY = rect[1] - t0 * fullH;
  const next = [originX + l * fullW, originY + t * fullH, originX + (1 - r) * fullW, originY + (1 - b) * fullH];
  return page ? clampRectToPage(next, page) : next;
}

/** 90도 돌릴 때: 가운데는 그대로, 가로·세로를 맞바꾼다. 쪽보다 커지면 비율대로 줄인다. */
export function rectAfterRotate(rect, page) {
  const { width, height } = rectSize(rect);
  const cx = (rect[0] + rect[2]) / 2;
  const cy = (rect[1] + rect[3]) / 2;
  return clampRectToPage([cx - height / 2, cy - width / 2, cx + height / 2, cy + width / 2], page);
}

/** 비율을 지킨 채 가로를 정한다(왼쪽 위 고정). 최소·쪽 크기로 제한한다. */
export function setWidth(rect, aspect, page, widthPt) {
  const [, , pw, ph] = page;
  const minW = aspect >= 1 ? MIN_SIDE * aspect : MIN_SIDE;
  const maxW = Math.min(pw, ph * aspect);
  const width = clamp(widthPt, Math.min(minW, maxW), maxW);
  return clampRectToPage([rect[0], rect[1], rect[0] + width, rect[1] + width / aspect], page);
}

export function setHeight(rect, aspect, page, heightPt) {
  return setWidth(rect, aspect, page, heightPt * aspect);
}

/** 위치를 정한다(왼쪽 위 기준, 쪽 안으로 제한). */
export function setPosition(rect, page, x, y) {
  const { width, height } = rectSize(rect);
  const nx = Number.isFinite(x) ? x : rect[0];
  const ny = Number.isFinite(y) ? y : rect[1];
  return clampRectToPage([nx, ny, nx + width, ny + height], page);
}

/** 크기 프리셋. 가운데를 지키며 크기를 바꾼다. */
export function presetRect(rect, aspect, page, mode, originalPx) {
  const [px0, py0, pw, ph] = page;
  const cx = (rect[0] + rect[2]) / 2;
  const cy = (rect[1] + rect[3]) / 2;
  const { width } = rectSize(rect);
  let target = width;
  if (mode === 'fitWidth') target = pw;
  else if (mode === 'fitHeight') target = ph * aspect;
  else if (mode === 'contain') target = Math.min(pw, ph * aspect);
  else if (mode === 'half') target = width * 0.5;
  else if (mode === 'double') target = width * 2;
  else if (mode === 'original') target = Math.max(1, (originalPx?.width ?? 0) * PT_PER_PX) || width;
  const minW = aspect >= 1 ? MIN_SIDE * aspect : MIN_SIDE;
  const maxW = Math.min(pw, ph * aspect);
  target = clamp(target, Math.min(minW, maxW), maxW);
  const half = target / 2;
  const halfH = target / aspect / 2;
  return clampRectToPage([cx - half, cy - halfH, cx + half, cy + halfH], [px0, py0, pw, ph]);
}

/** 쪽을 기준으로 정렬. how: left|centerX|right|top|centerY|bottom|center */
export function alignRect(rect, page, how) {
  const [px0, py0, pw, ph] = page;
  const { width, height } = rectSize(rect);
  let x = rect[0];
  let y = rect[1];
  if (how === 'left') x = px0;
  else if (how === 'right') x = px0 + pw - width;
  else if (how === 'centerX' || how === 'center') x = px0 + (pw - width) / 2;
  if (how === 'top') y = py0;
  else if (how === 'bottom') y = py0 + ph - height;
  else if (how === 'centerY' || how === 'center') y = py0 + (ph - height) / 2;
  return [x, y, x + width, y + height];
}

/** 여러 개를 하나의 묶음으로 보고 같이 옮긴다. 묶음이 쪽 밖으로 나가지 않게 이동량을 제한한다. */
export function moveGroup(rects, dx, dy, page) {
  const [px0, py0, pw, ph] = page;
  const minX = Math.min(...rects.map((r) => r[0]));
  const minY = Math.min(...rects.map((r) => r[1]));
  const maxX = Math.max(...rects.map((r) => r[2]));
  const maxY = Math.max(...rects.map((r) => r[3]));
  const gx = clamp(dx, px0 - minX, px0 + pw - maxX);
  const gy = clamp(dy, py0 - minY, py0 + ph - maxY);
  return rects.map((r) => [r[0] + gx, r[1] + gy, r[2] + gx, r[3] + gy]);
}

/**
 * 옮길 때 가장자리·가운데가 쪽 가장자리/가운데, 다른 이미지의 가장자리/가운데에 붙게 한다.
 * targets: { xs: number[], ys: number[] } 후보 선. threshold: pt.
 * 반환: { rect, guides: [{ axis: 'x'|'y', pos }] }
 */
export function snapMoveRect(rect, targets, threshold) {
  const { width, height } = rectSize(rect);
  const best = (points, candidates) => {
    let delta = null;
    let line = null;
    for (const point of points) {
      for (const candidate of candidates) {
        const d = candidate - point;
        if (Math.abs(d) <= threshold && (delta === null || Math.abs(d) < Math.abs(delta))) {
          delta = d;
          line = candidate;
        }
      }
    }
    return { delta, line };
  };
  const snapX = best([rect[0], (rect[0] + rect[2]) / 2, rect[2]], targets.xs);
  const snapY = best([rect[1], (rect[1] + rect[3]) / 2, rect[3]], targets.ys);
  const x0 = rect[0] + (snapX.delta ?? 0);
  const y0 = rect[1] + (snapY.delta ?? 0);
  const guides = [];
  if (snapX.line !== null) guides.push({ axis: 'x', pos: snapX.line });
  if (snapY.line !== null) guides.push({ axis: 'y', pos: snapY.line });
  return { rect: [x0, y0, x0 + width, y0 + height], guides };
}

/** 스냅 후보 선: 쪽 가장자리·가운데 + 다른 이미지 rect 들의 가장자리·가운데. */
export function snapTargets(page, otherRects) {
  const [px0, py0, pw, ph] = page;
  const xs = [px0, px0 + pw / 2, px0 + pw];
  const ys = [py0, py0 + ph / 2, py0 + ph];
  for (const r of otherRects) {
    xs.push(r[0], (r[0] + r[2]) / 2, r[2]);
    ys.push(r[1], (r[1] + r[3]) / 2, r[3]);
  }
  return { xs, ys };
}

/** 방향키 이동. step 은 pt. */
export function nudge(rect, key, step, page) {
  const dx = key === 'ArrowLeft' ? -step : key === 'ArrowRight' ? step : 0;
  const dy = key === 'ArrowUp' ? -step : key === 'ArrowDown' ? step : 0;
  return moveRect(rect, dx, dy, page);
}

/** "1-3, 5" → [0,1,2,4] (0부터). 범위를 벗어난 값은 버리고 중복을 없앤다. 비면 []. */
export function parsePageRange(text, pageCount) {
  const out = new Set();
  for (const part of String(text || '').split(/[,\s]+/)) {
    if (!part) continue;
    const m = /^(\d+)(?:\s*[-~]\s*(\d+))?$/.exec(part.trim());
    if (!m) continue;
    const a = Number(m[1]);
    const b = m[2] ? Number(m[2]) : a;
    for (let n = Math.min(a, b); n <= Math.max(a, b); n += 1) {
      if (n >= 1 && n <= pageCount) out.add(n - 1);
    }
  }
  return [...out].sort((x, y) => x - y);
}

/** 붙여넣을 위치: 같은 쪽이면 겹치지 않게 조금씩 밀고, 다른 쪽이면 같은 자리. */
export function pasteRect(rect, sameBase, count, page) {
  const shift = sameBase ? 14 * (count + 1) : 0;
  return clampRectToPage([rect[0] + shift, rect[1] + shift, rect[2] + shift, rect[3] + shift], page);
}
