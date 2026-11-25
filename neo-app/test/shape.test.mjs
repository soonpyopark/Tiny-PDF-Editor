import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clampDelta,
  dragHandle,
  hitShape,
  moveGeom,
  pickShape,
  polygonContains,
  rectFromDrag,
  sameGeom,
  shapeBounds,
  shapeHandles,
  snapAngle,
} from '../src/features/editor/draw/shapeMath.js';
import { normalizeDrawState } from '../src/features/editor/draw/drawSettings.js';
import {
  DEFAULT_SHAPE_STYLES,
  SHAPE_KINDS,
  hasFill,
  normalizeShapeStyles,
  paramsToStyle,
  snapShapeOpacity,
  snapWidth,
  styleToParams,
} from '../src/features/editor/draw/shapeSettings.js';
import { pickInk } from '../src/features/editor/draw/inkPick.js';

const rect = (r, params = {}) => ({ id: 1, pageIndex: 0, kind: 'rect', rect: r, params: { width: 2, fill: null, ...params } });
const line = (points, kind = 'line', params = {}) => ({ id: 2, pageIndex: 0, kind, points, params: { width: 2, ...params } });

test('shape kinds: 8 tools with unique shortcut letters', () => {
  assert.equal(SHAPE_KINDS.length, 8);
  assert.equal(new Set(SHAPE_KINDS.map((kind) => kind.key)).size, 8);
  assert.deepEqual(SHAPE_KINDS.map((kind) => kind.key).join(''), 'LARVPOET');
});

test('hit: unfilled rect is hit near its outline only, filled rect inside too', () => {
  const hollow = rect([10, 10, 110, 60]);
  assert.equal(hitShape(hollow, 10, 30, 3), true);
  assert.equal(hitShape(hollow, 60, 35, 3), false);
  assert.equal(hitShape(hollow, 200, 200, 3), false);
  const solid = rect([10, 10, 110, 60], { fill: '#ff0000' });
  assert.equal(hitShape(solid, 60, 35, 3), true);
});

test('hit: line and arrow use distance to the segment', () => {
  const l = line([[0, 0], [100, 0]]);
  assert.equal(hitShape(l, 50, 3, 3), true);
  assert.equal(hitShape(l, 50, 9, 3), false);
  assert.equal(hitShape(l, 130, 0, 3), false);
  assert.equal(hitShape(line([[0, 0], [100, 0]], 'arrow'), 50, 7, 3), true);
});

test('hit: ellipse outline and polygon fill', () => {
  const e = { id: 3, pageIndex: 0, kind: 'ellipse', rect: [0, 0, 100, 60], params: { width: 2, fill: null } };
  assert.equal(hitShape(e, 0, 30, 3), true);
  assert.equal(hitShape(e, 50, 30, 3), false);
  assert.equal(hitShape({ ...e, params: { width: 2, fill: '#000000' } }, 50, 30, 3), true);
  const p = { id: 4, pageIndex: 0, kind: 'polygon', points: [[0, 0], [100, 0], [50, 80]], params: { width: 2, fill: '#00ff00' } };
  assert.equal(hitShape(p, 50, 20, 3), true);
  assert.equal(hitShape(p, 95, 70, 3), false);
  assert.equal(polygonContains(p.points, 50, 20), true);
});

test('hit: text box is hit anywhere inside', () => {
  const t = { id: 5, pageIndex: 0, kind: 'text', rect: [10, 10, 110, 60], params: { width: 0, fill: null } };
  assert.equal(hitShape(t, 60, 35, 3), true);
  assert.equal(hitShape(t, 120, 35, 3), false);
});

test('pick prefers the shape drawn last', () => {
  const below = rect([0, 0, 100, 100], { fill: '#111111' });
  const above = { ...rect([20, 20, 60, 60], { fill: '#222222' }), id: 9 };
  assert.equal(pickShape([below, above], 30, 30, 3).id, 9);
  assert.equal(pickShape([below, above], 90, 90, 3).id, 1);
  assert.equal(pickShape([below, above], 300, 300, 3), null);
});

test('move keeps the shape on the page', () => {
  const r = rect([10, 10, 60, 40]);
  assert.deepEqual(moveGeom(r, 20, 5, 200, 100).rect, [30, 15, 80, 45]);
  assert.deepEqual(moveGeom(r, -50, -50, 200, 100).rect, [0, 0, 50, 30]);
  assert.deepEqual(moveGeom(r, 500, 500, 200, 100).rect, [150, 70, 200, 100]);
  const l = line([[10, 10], [60, 40]]);
  assert.deepEqual(moveGeom(l, 5, 5, 200, 100).points, [[15, 15], [65, 45]]);
  assert.deepEqual(clampDelta([0, 0, 300, 300], 10, 10, 200, 100), [10, 10]); // 쪽보다 큰 도형은 그대로
});

test('handles: rect has 8, polyline has one per vertex; dragging reshapes', () => {
  const r = rect([10, 10, 110, 60]);
  assert.equal(shapeHandles(r).length, 8);
  assert.deepEqual(dragHandle(r, 'se', 150, 90, 300, 200).rect, [10, 10, 150, 90]);
  assert.deepEqual(dragHandle(r, 'nw', 0, 0, 300, 200).rect, [0, 0, 110, 60]);
  assert.deepEqual(dragHandle(r, 'e', 200, 500, 300, 200).rect, [10, 10, 200, 60]); // 가로만
  // 뒤집히지 않고 최소 크기에서 멈춘다
  const flipped = dragHandle(r, 'w', 500, 0, 600, 200).rect;
  assert.ok(flipped[2] - flipped[0] >= 4);
  const l = line([[0, 0], [10, 10], [20, 0]], 'polyline');
  assert.equal(shapeHandles(l).length, 3);
  assert.deepEqual(dragHandle(l, 'p1', 12, 30, 100, 100).points, [[0, 0], [12, 30], [20, 0]]);
});

test('bounds, drag rect, angle snapping', () => {
  assert.deepEqual(shapeBounds(line([[5, 9], [1, 20], [8, 2]], 'polyline')), [1, 2, 8, 20]);
  assert.deepEqual(rectFromDrag({ x: 50, y: 50 }, { x: 10, y: 20 }), [10, 20, 50, 50]);
  assert.deepEqual(rectFromDrag({ x: 10, y: 10 }, { x: 40, y: 20 }, true), [10, 10, 40, 40]);
  const snapped = snapAngle({ x: 0, y: 0 }, { x: 100, y: 12 });
  assert.ok(Math.abs(snapped.y) < 1e-6 && Math.abs(snapped.x - Math.hypot(100, 12)) < 1e-6);
  assert.equal(sameGeom({ rect: [1, 2, 3, 4] }, { rect: [1, 2, 3, 4.005] }), true);
  assert.equal(sameGeom({ rect: [1, 2, 3, 4] }, { points: [[1, 2]] }), false);
});

test('settings: normalize repairs saved values; text box has its own defaults', () => {
  const fresh = normalizeShapeStyles(null);
  assert.deepEqual(fresh, normalizeShapeStyles(undefined));
  assert.equal(fresh.text.width, 0);
  assert.equal(fresh.shape.width, 2);
  const repaired = normalizeShapeStyles({ shape: { color: 'red', fill: 'zzz', width: 999, opacity: 5, dash: 1 }, text: { fontSize: -3, width: -1 } });
  assert.equal(repaired.shape.color, DEFAULT_SHAPE_STYLES.shape.color);
  assert.equal(repaired.shape.fill, null);
  assert.equal(repaired.shape.width, 20);
  assert.equal(repaired.shape.opacity, 5);
  assert.equal(repaired.shape.dash, true);
  assert.equal(repaired.text.fontSize, 4);
  assert.equal(repaired.text.width, 0);
  assert.equal(snapWidth('shape', 0), 0.5);
  assert.equal(snapWidth('text', 0), 0);
  assert.equal(snapWidth('shape', 1.23), 1.2); // 직접 입력은 0.1 단위
  assert.equal(snapWidth('shape', 'x'), 2);
  assert.equal(snapShapeOpacity(73.4), 73); // 투명도는 1% 단위
  assert.equal(snapShapeOpacity(1), 5);
  assert.equal(snapShapeOpacity(500), 100);
});

test('settings: style <-> engine params', () => {
  const style = { color: '#112233', fill: '#ffffff', width: 3, opacity: 50, dash: true, textColor: '#000000', fontSize: 16 };
  const p = styleToParams('rect', style);
  assert.equal(p.opacity, 0.5);
  assert.equal(p.fill, '#ffffff');
  assert.equal('fontSize' in p, false);
  assert.equal(styleToParams('line', style).fill, null); // 선은 채우기 없음
  assert.equal(styleToParams('text', style).fontSize, 16);
  assert.equal(paramsToStyle({ color: '#112233', fill: null, width: 3, opacity: 0.5 }).opacity, 50);
  assert.equal(hasFill('polyline'), false);
  assert.equal(hasFill('cloud'), true);
});

test('draw state: shape tools are valid saved tools; broken shape settings are repaired', () => {
  assert.equal(normalizeDrawState({ tool: 'select' }).tool, 'select');
  assert.equal(normalizeDrawState({ tool: 'cloud' }).tool, 'cloud');
  assert.equal(normalizeDrawState({ tool: 'star' }).tool, 'pen');
  assert.equal(normalizeDrawState({ lastShape: 'arrow' }).lastShape, 'arrow');
  assert.equal(normalizeDrawState({ lastShape: 'x' }).lastShape, 'rect');
  assert.equal(normalizeDrawState({ shapes: 7 }).shapes.shape.width, 2);
  assert.equal(normalizeDrawState(null).tools.pen.thickness, 1.5); // 기존 펜 설정은 그대로
});

test('pickInk: hits stroke within width+slack and prefers the last drawn', () => {
  const below = {
    id: 1,
    width: 4,
    strokes: [
      [
        [10, 10],
        [100, 10],
      ],
    ],
  };
  const above = {
    id: 2,
    width: 4,
    strokes: [
      [
        [40, 10],
        [40, 80],
      ],
    ],
  };
  assert.equal(pickInk([below, above], 40, 10, 3).id, 2);
  assert.equal(pickInk([below, above], 70, 10, 3).id, 1);
  assert.equal(pickInk([below, above], 70, 40, 3), null);
  assert.equal(pickInk([below], 70, 12, 1).id, 1); // width/2 + slack = 3
  assert.equal(pickInk([below], 70, 20, 1), null);
});
