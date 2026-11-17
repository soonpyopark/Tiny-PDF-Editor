import assert from 'node:assert/strict';
import test from 'node:test';
import {
  alignRect,
  applyLocalPatch,
  moveGroup,
  needsEngine,
  normalizeCrop,
  nudge,
  parsePageRange,
  pasteRect,
  presetRect,
  rectAfterCrop,
  rectAfterRotate,
  setHeight,
  setPosition,
  setWidth,
  snapMoveRect,
  snapTargets,
  visibleAspect,
} from '../src/features/editor/imageEditMath.js';

const PAGE = [0, 0, 400, 300];
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;
const w = (r) => r[2] - r[0];
const h = (r) => r[3] - r[1];
const params = (extra = {}) => ({ ow: 200, oh: 100, rot: 0, crop: [0, 0, 0, 0], op: 100, ...extra });

test('visibleAspect: 회전과 자르기를 반영한다', () => {
  assert.ok(near(visibleAspect(params()), 2));
  assert.ok(near(visibleAspect(params({ rot: 90 })), 0.5));
  assert.ok(near(visibleAspect(params({ crop: [0.25, 0, 0.25, 0] })), 1));
  assert.ok(near(visibleAspect(params({ crop: [0, 0.5, 0, 0] })), 4));
});

test('normalizeCrop: 합이 95% 를 넘지 않는다', () => {
  const [l, , r] = normalizeCrop([0.8, 0, 0.8, 0]);
  assert.ok(near(l + r, 0.95));
  assert.deepEqual(normalizeCrop('x'), [0, 0, 0, 0]);
});

test('applyLocalPatch: 투명도는 5~100, 자르기 초기화', () => {
  assert.equal(applyLocalPatch(params(), { op: 1 }).op, 5);
  assert.equal(applyLocalPatch(params(), { op: 300 }).op, 100);
  assert.deepEqual(applyLocalPatch(params({ crop: [0.1, 0.1, 0.1, 0.1] }), { cropReset: true }).crop, [0, 0, 0, 0]);
  assert.equal(applyLocalPatch(params(), { lock: true }).lock, true);
  assert.equal(needsEngine({ op: 50 }), false);
  assert.equal(needsEngine({ bg: { on: true } }), true);
  assert.equal(needsEngine({ rotate: 90 }), true);
});

test('rectAfterCrop: 배율은 그대로, 보이는 영역만 달라진다', () => {
  const rect = [100, 100, 300, 200]; // 200 x 100
  const next = rectAfterCrop(rect, [0, 0, 0, 0], [0.25, 0, 0.25, 0], PAGE);
  assert.ok(near(w(next), 100));
  assert.ok(near(h(next), 100));
  assert.ok(near(next[0], 150));
  // 자르기를 되돌리면 원래 rect 로 돌아온다
  const back = rectAfterCrop(next, [0.25, 0, 0.25, 0], [0, 0, 0, 0], PAGE);
  rect.forEach((v, i) => assert.ok(near(v, back[i], 1e-9)));
  // 자른 뒤의 비율 = 새 rect 의 비율
  assert.ok(near(w(next) / h(next), visibleAspect(params({ crop: [0.25, 0, 0.25, 0] }))));
});

test('rectAfterRotate: 가운데를 지키며 가로 세로를 맞바꾼다', () => {
  const rect = [100, 100, 300, 200];
  const next = rectAfterRotate(rect, PAGE);
  assert.ok(near(w(next), 100) && near(h(next), 200));
  assert.ok(near((next[0] + next[2]) / 2, 200) && near((next[1] + next[3]) / 2, 150));
  // 쪽보다 커지면 줄인다
  const tall = rectAfterRotate([0, 0, 400, 100], PAGE);
  assert.ok(h(tall) <= 300 + 1e-9 && w(tall) <= 400 + 1e-9);
});

test('setWidth/setHeight: 비율을 지키고 쪽 안에 머문다', () => {
  const rect = [50, 50, 150, 100]; // aspect 2
  const next = setWidth(rect, 2, PAGE, 200);
  assert.ok(near(w(next), 200) && near(h(next), 100));
  assert.ok(near(next[0], 50) && near(next[1], 50));
  const huge = setWidth(rect, 2, PAGE, 5000);
  assert.ok(w(huge) <= 400 + 1e-9 && h(huge) <= 300 + 1e-9);
  assert.ok(near(w(huge) / h(huge), 2));
  const byHeight = setHeight(rect, 2, PAGE, 60);
  assert.ok(near(h(byHeight), 60) && near(w(byHeight), 120));
  // 너무 작게는 못 줄인다
  assert.ok(h(setWidth(rect, 2, PAGE, 1)) >= 16 - 1e-9);
});

test('setPosition: 쪽 밖으로 나가지 않는다', () => {
  const rect = [0, 0, 100, 50];
  const next = setPosition(rect, PAGE, 380, -20);
  assert.ok(near(next[2], 400) && near(next[1], 0));
  const keepX = setPosition(rect, PAGE, NaN, 40);
  assert.ok(near(keepX[0], 0) && near(keepX[1], 40));
});

test('presetRect: 쪽 맞춤/절반/두 배/원본', () => {
  const rect = [100, 100, 200, 150]; // 100 x 50, aspect 2
  const fitW = presetRect(rect, 2, PAGE, 'fitWidth');
  assert.ok(near(w(fitW), 400) && near(h(fitW), 200));
  const fitH = presetRect(rect, 2, PAGE, 'fitHeight');
  assert.ok(near(h(fitH), 200) && near(w(fitH), 400)); // ph*aspect=600 → 쪽 폭 400 으로 제한
  const contain = presetRect(rect, 2, PAGE, 'contain');
  assert.ok(near(w(contain), 400));
  const half = presetRect(rect, 2, PAGE, 'half');
  assert.ok(near(w(half), 50) && near((half[0] + half[2]) / 2, 150));
  const dbl = presetRect(rect, 2, PAGE, 'double');
  assert.ok(near(w(dbl), 200));
  const orig = presetRect(rect, 2, PAGE, 'original', { width: 160, height: 80 });
  assert.ok(near(w(orig), 120));
});

test('alignRect: 쪽 기준 정렬', () => {
  const rect = [100, 100, 200, 150];
  assert.ok(near(alignRect(rect, PAGE, 'left')[0], 0));
  assert.ok(near(alignRect(rect, PAGE, 'right')[2], 400));
  assert.ok(near(alignRect(rect, PAGE, 'top')[1], 0));
  assert.ok(near(alignRect(rect, PAGE, 'bottom')[3], 300));
  const c = alignRect(rect, PAGE, 'center');
  assert.ok(near((c[0] + c[2]) / 2, 200) && near((c[1] + c[3]) / 2, 150));
  const cx = alignRect(rect, PAGE, 'centerX');
  assert.ok(near(cx[1], 100));
});

test('moveGroup: 묶음이 쪽 밖으로 나가지 않고 간격을 지킨다', () => {
  const rects = [
    [10, 10, 60, 40],
    [100, 100, 160, 140],
  ];
  const moved = moveGroup(rects, -50, -50, PAGE);
  assert.ok(near(moved[0][0], 0) && near(moved[0][1], 0));
  assert.ok(near(moved[1][0] - moved[0][0], 90)); // 간격 그대로
  const right = moveGroup(rects, 1000, 0, PAGE);
  assert.ok(near(right[1][2], 400));
});

test('snapMoveRect: 가까우면 붙고 멀면 그대로', () => {
  const targets = snapTargets(PAGE, [[200, 50, 260, 90]]);
  const rect = [3, 100, 53, 140]; // 왼쪽 가장자리가 쪽 왼쪽(0)에 3pt 차이
  const snapped = snapMoveRect(rect, targets, 6);
  assert.ok(near(snapped.rect[0], 0));
  assert.ok(snapped.guides.some((g) => g.axis === 'x' && g.pos === 0));
  assert.ok(near(w(snapped.rect), 50) && near(h(snapped.rect), 40));
  const far = snapMoveRect([20, 100, 70, 140], targets, 6);
  assert.deepEqual(far.rect, [20, 100, 70, 140]);
  assert.equal(far.guides.length, 0);
  // 가운데 맞춤: 가로 가운데가 200 에 가깝게
  const mid = snapMoveRect([176, 100, 226, 140], targets, 6);
  assert.ok(near((mid.rect[0] + mid.rect[2]) / 2, 200));
});

test('nudge: 방향키 이동은 쪽 안에서 멈춘다', () => {
  assert.deepEqual(nudge([10, 10, 60, 40], 'ArrowRight', 1, PAGE), [11, 10, 61, 40]);
  assert.deepEqual(nudge([0, 0, 50, 30], 'ArrowLeft', 10, PAGE), [0, 0, 50, 30]);
  assert.deepEqual(nudge([10, 10, 60, 40], 'ArrowDown', 10, PAGE), [10, 20, 60, 50]);
});

test('parsePageRange: 범위/쉼표/중복/벗어난 값', () => {
  assert.deepEqual(parsePageRange('1-3, 5', 10), [0, 1, 2, 4]);
  assert.deepEqual(parsePageRange('3-1', 10), [0, 1, 2]);
  assert.deepEqual(parsePageRange('2,2,99,abc', 5), [1]);
  assert.deepEqual(parsePageRange('', 5), []);
});

test('pasteRect: 같은 쪽이면 밀고, 다른 쪽이면 같은 자리', () => {
  const rect = [10, 10, 60, 40];
  assert.deepEqual(pasteRect(rect, true, 0, PAGE), [24, 24, 74, 54]);
  assert.deepEqual(pasteRect(rect, true, 1, PAGE), [38, 38, 88, 68]);
  assert.deepEqual(pasteRect(rect, false, 3, PAGE), rect);
});
