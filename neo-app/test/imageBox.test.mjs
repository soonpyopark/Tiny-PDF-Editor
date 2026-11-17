import assert from 'node:assert/strict';
import test from 'node:test';
import {
  MIN_SIDE,
  clampRectToPage,
  handlePoint,
  minWidthFor,
  moveRect,
  resizeRect,
  styleFromRect,
} from '../src/features/editor/imageBoxMath.js';

const PAGE = [0, 0, 400, 300];
const ASPECT = 2; // 가로가 세로의 2배
const ORIGIN = [100, 100, 200, 150]; // 100 x 50
const HANDLE_NAMES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

const w = (r) => r[2] - r[0];
const h = (r) => r[3] - r[1];
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

test('모든 핸들: 아무리 끌어도 비율이 유지된다', () => {
  const points = [];
  for (let x = -50; x <= 450; x += 25) for (let y = -50; y <= 350; y += 25) points.push({ x, y });
  for (const handle of HANDLE_NAMES) {
    for (const point of points) {
      const r = resizeRect(ORIGIN, handle, point, ASPECT, PAGE);
      assert.ok(near(w(r) / h(r), ASPECT, 1e-6), `${handle} ${point.x},${point.y} -> ${r}`);
    }
  }
});

test('모든 핸들: 최소 크기(짧은 변 MIN_SIDE) 아래로 줄지 않고 뒤집히지 않는다', () => {
  for (const handle of HANDLE_NAMES) {
    const [hx, hy] = handlePoint(ORIGIN, handle);
    // 반대편 너머로 끌기
    const far = { x: ORIGIN[0] + (ORIGIN[2] - hx) * 3 - (hx - ORIGIN[0]), y: ORIGIN[1] + (ORIGIN[3] - hy) * 3 - (hy - ORIGIN[1]) };
    const r = resizeRect(ORIGIN, handle, far, ASPECT, PAGE);
    assert.ok(h(r) >= MIN_SIDE - 1e-6, `${handle} h=${h(r)}`);
    assert.ok(w(r) >= minWidthFor(ASPECT) - 1e-6, `${handle} w=${w(r)}`);
    assert.ok(r[2] > r[0] && r[3] > r[1], `${handle} flipped ${r}`);
  }
});

test('모서리: 반대쪽 모서리가 움직이지 않는다', () => {
  const fixed = { nw: [200, 150], ne: [100, 150], se: [100, 100], sw: [200, 100] };
  for (const [handle, [fx, fy]] of Object.entries(fixed)) {
    const [hx, hy] = handlePoint(ORIGIN, handle);
    const r = resizeRect(ORIGIN, handle, { x: hx + (fx < hx ? 40 : -40), y: hy + (fy < hy ? 20 : -20) }, ASPECT, PAGE);
    const opposite = { nw: [r[2], r[3]], ne: [r[0], r[3]], se: [r[0], r[1]], sw: [r[2], r[1]] }[handle];
    assert.ok(near(opposite[0], fx) && near(opposite[1], fy), `${handle}: ${opposite} != ${fx},${fy}`);
  }
});

test('모서리: 커서가 핸들 위에 그대로 붙어 따라온다 (비율에 맞는 위치로 끌 때)', () => {
  // se 핸들(200,150)을 (260,180)=정확히 2:1 로 늘어나는 점으로 끌면 핸들이 그 점에 와야 한다.
  const r = resizeRect(ORIGIN, 'se', { x: 260, y: 180 }, ASPECT, PAGE);
  assert.ok(near(r[2], 260) && near(r[3], 180), String(r));
});

test('잡은 자리 보정(grab): 핸들 중심에서 3px 어긋나게 잡아도 처음엔 상자가 튀지 않는다', () => {
  const grab = { x: 3, y: -2 };
  const r = resizeRect(ORIGIN, 'se', { x: 200 + 3, y: 150 - 2 }, ASPECT, PAGE, grab);
  assert.deepEqual(r.map((v) => Math.round(v * 1000) / 1000), ORIGIN);
});

test('쪽 경계에서는 상자를 밀지 않고 거기서 멈춘다 (고정 모서리 유지)', () => {
  const r = resizeRect(ORIGIN, 'se', { x: 900, y: 900 }, ASPECT, PAGE);
  assert.ok(near(r[0], 100) && near(r[1], 100));
  assert.ok(r[2] <= 400 + 1e-6 && r[3] <= 300 + 1e-6, String(r));
  assert.ok(near(w(r) / h(r), ASPECT));
  const nw = resizeRect(ORIGIN, 'nw', { x: -500, y: -500 }, ASPECT, PAGE);
  assert.ok(nw[0] >= -1e-6 && nw[1] >= -1e-6 && near(nw[2], 200) && near(nw[3], 150), String(nw));
});

test('변 핸들: 그 축으로만 크기가 정해지고 반대 변은 고정, 다른 축은 가운데 유지', () => {
  const e = resizeRect(ORIGIN, 'e', { x: 300, y: 999 }, ASPECT, PAGE);
  assert.ok(near(e[0], 100) && near(w(e), 200) && near(h(e), 100));
  assert.ok(near((e[1] + e[3]) / 2, 125));
  const n = resizeRect(ORIGIN, 'n', { x: -999, y: 50 }, ASPECT, PAGE);
  assert.ok(near(n[3], 150) && near(h(n), 100) && near(w(n), 200));
  assert.ok(near((n[0] + n[2]) / 2, 150));
});

test('이동: 쪽 안에 머문다', () => {
  assert.deepEqual(moveRect(ORIGIN, -500, -500, PAGE), [0, 0, 100, 50]);
  assert.deepEqual(moveRect(ORIGIN, 900, 900, PAGE), [300, 250, 400, 300]);
  assert.deepEqual(moveRect(ORIGIN, 10, 20, PAGE), [110, 120, 210, 170]);
});

test('clampRectToPage: 쪽보다 큰 상자는 비율을 지키며 줄인다', () => {
  const r = clampRectToPage([-100, -100, 700, 100], PAGE);
  assert.ok(w(r) <= 400 + 1e-6 && near(w(r) / h(r), 4));
});

test('화면 스타일은 보정 없이 rect 를 그대로 퍼센트로 쓴다 (WYSIWYG: 작은 상자도 찌그러지지 않음)', () => {
  const tiny = [10, 10, 10 + 32, 10 + 16]; // 2:1, 쪽 대비 8% 미만
  const s = styleFromRect(tiny, PAGE);
  assert.equal(parseFloat(s.width), (32 / 400) * 100);
  assert.equal(parseFloat(s.height), (16 / 300) * 100);
  // 화면 픽셀 비율 = 쪽 비율 보정 후 2:1
  assert.ok(near((parseFloat(s.width) * 400) / (parseFloat(s.height) * 300), 2, 1e-9));
});
