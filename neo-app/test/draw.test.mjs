// 그리기 순수 로직 테스트: node --test test/
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DEFAULT_TOOL_SETTINGS,
  hexToRgb01,
  normalizeDrawState,
  snapEraserRadius,
  snapOpacity,
  snapThickness,
} from '../src/features/editor/draw/drawSettings.js';
import {
  catmullRomSpline,
  finalizeStroke,
  simplifyPoints,
  thinPoints,
} from '../src/features/editor/draw/strokeMath.js';

const P = (x, y) => ({ x, y });

test('thinPoints drops near points but keeps the last one', () => {
  const out = thinPoints([P(0, 0), P(0.1, 0), P(0.2, 0), P(5, 0), P(5.05, 0)], 1);
  assert.deepEqual(out.map((p) => p.x), [0, 5, 5.05]);
});

test('simplifyPoints removes collinear points and keeps corners', () => {
  const line = Array.from({ length: 50 }, (_, i) => P(i, 0));
  assert.equal(simplifyPoints(line, 0.1).length, 2);
  const corner = [...Array.from({ length: 20 }, (_, i) => P(i, 0)), ...Array.from({ length: 20 }, (_, i) => P(19, i + 1))];
  const simplified = simplifyPoints(corner, 0.1);
  assert.equal(simplified.length, 3);
  assert.deepEqual(simplified[1], P(19, 0));
});

test('simplifyPoints survives a very long stroke without recursion overflow', () => {
  const long = Array.from({ length: 200000 }, (_, i) => P(i, Math.sin(i / 50) * 20));
  const out = simplifyPoints(long, 0.2);
  assert.ok(out.length > 2 && out.length < long.length);
});

test('catmullRomSpline passes through the control points', () => {
  const pts = [P(0, 0), P(10, 10), P(20, 0), P(30, 10)];
  const spline = catmullRomSpline(pts, 6);
  assert.equal(spline.length, 1 + 3 * 6);
  for (let i = 0; i < pts.length; i += 1) {
    const s = spline[i * 6];
    assert.ok(Math.abs(s.x - pts[i].x) < 1e-9 && Math.abs(s.y - pts[i].y) < 1e-9);
  }
});

test('finalizeStroke: tap stays one point, short stroke stays short, long stroke is smoothed', () => {
  assert.deepEqual(finalizeStroke([P(3, 4)], 2), [[3, 4]]);
  assert.equal(finalizeStroke([P(0, 0), P(10, 0)], 2).length, 2);
  const wiggle = Array.from({ length: 30 }, (_, i) => P(i * 3, (i % 2) * 2));
  const out = finalizeStroke(wiggle, 2);
  assert.ok(out.length >= 3);
  for (const [x, y] of out) assert.ok(Number.isFinite(x) && Number.isFinite(y));
  assert.deepEqual(finalizeStroke([], 2), []);
});

test('snapOpacity / snapThickness / snapEraserRadius clamp and snap', () => {
  assert.equal(snapOpacity(73), 70);
  assert.equal(snapOpacity(-5), 10);
  assert.equal(snapOpacity(0), 10);
  assert.equal(snapOpacity('x'), 100);
  assert.equal(snapOpacity(500), 100);
  assert.equal(snapThickness('pen', 0.1), 0.5);
  assert.equal(snapThickness('pen', 9), 6);
  assert.equal(snapThickness('pen', 1.7), 1.5);
  assert.equal(snapThickness('highlighter', 3), 10);
  assert.equal(snapThickness('highlighter', 33), 35);
  assert.equal(snapThickness('pen', 'abc'), 1.5);
  assert.equal(snapEraserRadius(1), 4);
  assert.equal(snapEraserRadius(999), 40);
});

test('hexToRgb01 handles bad input', () => {
  assert.deepEqual(hexToRgb01('#ff0000'), [1, 0, 0]);
  const [r, g, b] = hexToRgb01('nonsense');
  assert.ok([r, g, b].every((v) => v >= 0 && v <= 1));
});

test('normalizeDrawState repairs broken saved state', () => {
  const fresh = normalizeDrawState(null);
  assert.equal(fresh.tool, 'pen');
  assert.deepEqual(fresh.tools.pen, DEFAULT_TOOL_SETTINGS.pen);
  const repaired = normalizeDrawState({ tool: 'laser', tools: { pen: { thickness: 99, opacity: 'x', color: 'red' } }, eraserRadius: -1 });
  assert.equal(repaired.tool, 'pen');
  assert.equal(repaired.tools.pen.thickness, 6);
  assert.equal(repaired.tools.pen.opacity, 100);
  assert.equal(repaired.tools.pen.color, DEFAULT_TOOL_SETTINGS.pen.color);
  assert.equal(repaired.eraserRadius, 4);
  assert.equal(normalizeDrawState({ tool: 'highlighter' }).tool, 'highlighter');
});
