// 그리기 획 다듬기. Whiteboard4Share 의 smoothing.ts / strokeSimplify.ts / strokeInput.ts(thin) 를
// 압력 값 없이 옮긴 것이다. PDF 잉크 주석은 획마다 선 두께가 하나이고 선분으로만 이어지므로
// 압력은 쓰지 않고, 손떨림은 줄이되 촘촘한 점으로 곡선을 근사한다.
//
// 점은 모두 { x, y }. 좌표 단위는 호출하는 쪽이 정한다(여기서는 PDF pt).

/** 앞 점과 minDist 보다 가까운 점은 버린다. 마지막 점은 남긴다. */
export function thinPoints(points, minDist) {
  if (points.length <= 1 || minDist <= 0) return points.slice();
  const out = [points[0]];
  for (let i = 1; i < points.length; i += 1) {
    const prev = out[out.length - 1];
    if (Math.hypot(points[i].x - prev.x, points[i].y - prev.y) >= minDist) out.push(points[i]);
  }
  const last = points[points.length - 1];
  const tail = out[out.length - 1];
  if (Math.hypot(last.x - tail.x, last.y - tail.y) > 0.01) out.push(last);
  return out;
}

function catmullRomPoint(p0, p1, p2, p3, t) {
  const t2 = t * t;
  const t3 = t2 * t;
  const x =
    0.5 *
    (2 * p1.x +
      (-p0.x + p2.x) * t +
      (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 +
      (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3);
  const y =
    0.5 *
    (2 * p1.y +
      (-p0.y + p2.y) * t +
      (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 +
      (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3);
  return { x, y };
}

/** Catmull-Rom 스플라인으로 점 사이를 부드럽게 채운다. */
export function catmullRomSpline(points, segmentsPerSpan = 6) {
  if (points.length < 2) return points.slice();
  if (points.length === 2) {
    const [a, b] = points;
    const out = [a];
    for (let i = 1; i <= segmentsPerSpan; i += 1) {
      const t = i / segmentsPerSpan;
      out.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
    }
    return out;
  }
  const out = [points[0]];
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[Math.max(0, i - 1)];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[Math.min(points.length - 1, i + 2)];
    for (let t = 1; t <= segmentsPerSpan; t += 1) {
      out.push(catmullRomPoint(p0, p1, p2, p3, t / segmentsPerSpan));
    }
  }
  return out;
}

function pointToSegmentDistSq(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) {
    const ex = p.x - a.x;
    const ey = p.y - a.y;
    return ex * ex + ey * ey;
  }
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq));
  const ex = p.x - (a.x + t * dx);
  const ey = p.y - (a.y + t * dy);
  return ex * ex + ey * ey;
}

/** Ramer–Douglas–Peucker 단순화. 반복(스택) 방식이라 아주 긴 획에서도 호출 스택이 넘치지 않는다. */
export function simplifyPoints(points, epsilon) {
  if (points.length <= 2 || epsilon <= 0) return points.slice();
  const keep = new Uint8Array(points.length);
  keep[0] = 1;
  keep[points.length - 1] = 1;
  const epsilonSq = epsilon * epsilon;
  const stack = [[0, points.length - 1]];
  while (stack.length) {
    const [start, end] = stack.pop();
    if (end <= start + 1) continue;
    let maxDistSq = 0;
    let maxIndex = start;
    for (let i = start + 1; i < end; i += 1) {
      const d = pointToSegmentDistSq(points[i], points[start], points[end]);
      if (d > maxDistSq) {
        maxDistSq = d;
        maxIndex = i;
      }
    }
    if (maxDistSq > epsilonSq) {
      keep[maxIndex] = 1;
      stack.push([start, maxIndex], [maxIndex, end]);
    }
  }
  const out = [];
  for (let i = 0; i < points.length; i += 1) if (keep[i]) out.push(points[i]);
  return out.length >= 2 ? out : points.slice();
}

/**
 * 손으로 그린 원본 점들을 PDF 에 넣을 점으로 다듬는다.
 * 솎기 -> 스플라인 -> 단순화 순서. 점이 하나뿐이면(탭) 그대로 돌려줘 엔진이 점으로 찍게 한다.
 * @param {{x:number,y:number}[]} raw
 * @param {number} widthPt 선 두께(pt). 두꺼울수록 더 느슨하게 단순화한다.
 * @returns {number[][]} [[x, y], ...]
 */
export function finalizeStroke(raw, widthPt) {
  if (!raw.length) return [];
  const thinned = thinPoints(raw, 0.3);
  if (thinned.length < 3) return thinned.map((p) => [p.x, p.y]);
  const smooth = catmullRomSpline(thinned, 6);
  const epsilon = Math.max(0.08, Math.min(0.6, widthPt * 0.04));
  return simplifyPoints(smooth, epsilon).map((p) => [p.x, p.y]);
}

/** 실시간 미리보기용: 중간점 이차곡선으로 그릴 경로를 만든다 (canvas 2D). */
export function tracePath(ctx, points) {
  if (!points.length) return;
  ctx.moveTo(points[0].x, points[0].y);
  if (points.length === 1) {
    ctx.lineTo(points[0].x + 0.01, points[0].y);
    return;
  }
  for (let i = 1; i < points.length - 1; i += 1) {
    const mx = (points[i].x + points[i + 1].x) / 2;
    const my = (points[i].y + points[i + 1].y) / 2;
    ctx.quadraticCurveTo(points[i].x, points[i].y, mx, my);
  }
  const last = points[points.length - 1];
  ctx.lineTo(last.x, last.y);
}
