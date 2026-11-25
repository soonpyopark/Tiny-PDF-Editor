import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  MIN_BOX,
  clampDelta,
  clampPoint,
  dragHandle,
  draftShape,
  geomOf,
  handleCursor,
  moveGeom,
  pickShape,
  rectFromDrag,
  sameGeom,
  shapeBounds,
  shapeHandles,
  snapAngle,
  withGeom,
} from './shapeMath.js';
import {
  inkBounds,
  inkHandleCursor,
  inkHandles,
  moveInk,
  pickInk,
  sameInkStrokes,
  scaleInk,
  withInkStrokes,
} from './inkPick.js';
import { pickLassoHits, selectionBounds } from './lassoPick.js';
import { CLOSED_KINDS, LASSO_TOOL, SELECT_TOOL, isPointKind } from './shapeSettings.js';

/**
 * 쪽 이미지 위에 겹치는 도형·잉크 선택 레이어.
 *
 * - 도형 자체는 PDF 주석으로 쪽 그림에 이미 그려져 있다. 이 레이어는 그리는 중 미리보기, 선택 표시(손잡이),
 *   끌어서 옮기거나 크기를 바꿀 때의 윤곽, 텍스트 상자 글 입력창만 맡는다.
 * - 도구가 '선택'이면 클릭으로 도형 또는 펜·연필·형광펜 획을 고른다. 둘 다 끌어 옮기고 손잡이로 크기를 바꾸며,
 *   Delete 로 지운다. 올가미로 여러 개를 고른 뒤에는 한꺼번에 옮기거나 지울 수 있다.
 * - 도구가 '올가미'이면 자유 곡선으로 감싸 경로에 닿거나 닫힌 영역 안의 잉크·도형을 고른다.
 * - 도구가 도형이면 끌어서(선·화살표·직사각형·타원형·텍스트 상자) 또는 점을 눌러서(다각형·클라우드·폴리라인) 그린다.
 * - 좌표는 쪽 화면 좌표(pt, 회전 반영). 배율이 바뀌어도 제 자리에 있다.
 */

const DEFAULT_TEXT_BOX = [160, 44];
const HANDLE_PX = 9;
const PICK_PX = 6;
const CLICK_PX = 3;

function dashFor(params) {
  if (!params.dash) return undefined;
  const unit = Math.max(1, params.width || 1);
  return `${unit * 3} ${unit * 2}`;
}

function arrowHead(a, b, width) {
  const length = Math.max(8, width * 4.5);
  const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
  const spread = Math.PI / 7;
  const p1 = [b[0] - length * Math.cos(angle - spread), b[1] - length * Math.sin(angle - spread)];
  const p2 = [b[0] - length * Math.cos(angle + spread), b[1] - length * Math.sin(angle + spread)];
  return `${b[0]},${b[1]} ${p1[0]},${p1[1]} ${p2[0]},${p2[1]}`;
}

/** 엔진이 그릴 모양을 비슷하게 흉내 낸 미리보기(그리는 중·끄는 중). */
function ShapePreview({ shape, opacity = 0.85 }) {
  const { kind, params } = shape;
  const width = Math.max(0.5, params.width || 0);
  const common = {
    stroke: params.color,
    strokeWidth: width,
    fill: params.fill || 'none',
    strokeDasharray: dashFor(params),
    strokeLinejoin: 'round',
    opacity: Math.min(opacity, params.opacity ?? 1),
  };
  if (kind === 'line' || kind === 'arrow' || kind === 'polyline') {
    const points = shape.points.map((p) => p.join(',')).join(' ');
    return (
      <g>
        <polyline {...common} fill="none" points={points} />
        {kind === 'arrow' ? <polygon points={arrowHead(shape.points[0], shape.points[1], width)} fill={params.color} stroke={params.color} strokeWidth={1} opacity={common.opacity} /> : null}
      </g>
    );
  }
  if (kind === 'polygon' || kind === 'cloud') {
    return <polygon {...common} strokeDasharray={kind === 'cloud' ? `${width * 1.4} ${width * 1.2}` : common.strokeDasharray} strokeLinecap={kind === 'cloud' ? 'round' : undefined} points={shape.points.map((p) => p.join(',')).join(' ')} />;
  }
  const [x0, y0, x1, y1] = shape.rect;
  if (kind === 'ellipse') {
    return <ellipse {...common} cx={(x0 + x1) / 2} cy={(y0 + y1) / 2} rx={(x1 - x0) / 2} ry={(y1 - y0) / 2} />;
  }
  if (kind === 'text') {
    return <rect {...common} fill={params.fill || 'rgba(255,255,255,0.4)'} stroke={params.width > 0 ? params.color : '#64748b'} strokeWidth={params.width > 0 ? width : 0.75} strokeDasharray={params.width > 0 ? undefined : '3 2'} x={x0} y={y0} width={x1 - x0} height={y1 - y0} />;
  }
  return <rect {...common} x={x0} y={y0} width={x1 - x0} height={y1 - y0} />;
}

function inkRgb(color) {
  if (!Array.isArray(color) || color.length < 3) return 'rgb(74,74,74)';
  const toByte = (v) => Math.round(Math.min(1, Math.max(0, Number(v) || 0)) * 255);
  return `rgb(${toByte(color[0])},${toByte(color[1])},${toByte(color[2])})`;
}

/** 옮기거나 크기를 바꾸는 중 보이는 잉크 미리보기. */
function InkPreview({ ink, opacity = 0.85 }) {
  const width = Math.max(0.5, Number(ink.width) || 1);
  const color = inkRgb(ink.color);
  const stored = Number(ink.opacity);
  const inkAlpha = Number.isFinite(stored) && stored >= 0 ? Math.min(1, stored) : 1;
  const alpha = Math.min(opacity, inkAlpha);
  return (
    <g opacity={alpha}>
      {(Array.isArray(ink.strokes) ? ink.strokes : []).map((stroke, index) => (
        <polyline
          key={index}
          points={(Array.isArray(stroke) ? stroke : []).map((p) => `${p[0]},${p[1]}`).join(' ')}
          fill="none"
          stroke={color}
          strokeWidth={width}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </g>
  );
}

export default function ShapeLayer({ pageIndex, ptW, ptH, tool, newParams, controller }) {
  const layerRef = useRef(null);
  const gestureRef = useRef(/** @type {any} */ (null));
  const [unit, setUnit] = useState(1); // 화면 1px 가 몇 pt 인가
  const [ghost, setGhost] = useState(/** @type {null | { shape: any, moving: boolean }} */ (null));
  const [poly, setPoly] = useState(/** @type {null | { points: number[][], hover: number[] | null }} */ (null));
  const polyRef = useRef(poly);
  polyRef.current = poly;
  const [hoverId, setHoverId] = useState(/** @type {number | null} */ (null));
  const [lassoPath, setLassoPath] = useState(/** @type {number[][] | null} */ (null));
  const isSelect = tool === SELECT_TOOL;
  const isLasso = tool === LASSO_TOOL;
  const shapes = controller.shapes[pageIndex] || [];
  const inks = controller.inks?.[pageIndex] || [];
  const pageSelection = (controller.selection || []).filter((item) => item.pageIndex === pageIndex);
  const multiSelect = pageSelection.length > 1;
  const selected =
    !multiSelect && controller.selected && controller.selected.pageIndex === pageIndex && controller.selected.kind !== 'ink'
      ? controller.selectedShape
      : null;
  const selectedInk =
    !multiSelect && controller.selected && controller.selected.pageIndex === pageIndex && controller.selected.kind === 'ink'
      ? controller.selectedInk
      : null;
  const editing = controller.textEdit && controller.textEdit.pageIndex === pageIndex ? controller.textEdit : null;
  const unionBounds = pageSelection.length ? selectionBounds(pageSelection, inks, shapes) : null;

  useLayoutEffect(() => {
    const el = layerRef.current;
    if (!el) return undefined;
    const measure = () => {
      const width = el.getBoundingClientRect().width;
      if (width > 0) setUnit(ptW / width);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ptW]);

  // 도구가 바뀌면 그리던 것은 버린다.
  useEffect(() => {
    gestureRef.current = null;
    setGhost(null);
    setPoly(null);
    setLassoPath(null);
    setHoverId(null);
  }, [tool]);

  function toPt(event) {
    const box = layerRef.current.getBoundingClientRect();
    return clampPoint({ x: ((event.clientX - box.left) / box.width) * ptW, y: ((event.clientY - box.top) / box.height) * ptH }, ptW, ptH);
  }

  const pxToPt = () => {
    const box = layerRef.current.getBoundingClientRect();
    return ptW / Math.max(1, box.width);
  };

  // ---- 점으로 그리는 도형(다각형·클라우드·폴리라인) 끝내기
  function finishPoly() {
    const current = polyRef.current;
    setPoly(null);
    if (!current || !tool) return;
    const need = CLOSED_KINDS.includes(tool) ? 3 : 2;
    if (current.points.length < need) return;
    void controller.create(pageIndex, tool, { points: current.points }, newParams);
  }

  useEffect(() => {
    if (!poly) return undefined;
    function onKeyDown(event) {
      const el = event.target;
      if (el instanceof HTMLTextAreaElement || (el instanceof HTMLInputElement && !['range', 'checkbox', 'radio', 'button', 'color'].includes(el.type))) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        setPoly(null);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        event.stopImmediatePropagation();
        finishPoly();
      } else if (event.key === 'Backspace' || event.key === 'Delete') {
        event.preventDefault();
        event.stopImmediatePropagation();
        setPoly((prev) => (prev && prev.points.length > 1 ? { ...prev, points: prev.points.slice(0, -1) } : null));
      }
    }
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Boolean(poly), tool, pageIndex]);

  // ---- 눌렀을 때
  function startGesture(event, gesture) {
    gestureRef.current = { pointerId: event.pointerId, ...gesture };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function onPointerDown(event) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (gestureRef.current) return;
    event.preventDefault();
    const point = toPt(event);
    const ppx = pxToPt();
    if (isLasso) {
      const inUnion =
        pageSelection.length > 0 &&
        unionBounds &&
        point.x >= unionBounds[0] &&
        point.x <= unionBounds[2] &&
        point.y >= unionBounds[1] &&
        point.y <= unionBounds[3];
      if (inUnion) {
        startGesture(event, { type: 'group-move', start: point, items: pageSelection, moved: false });
        return;
      }
      const start = [point.x, point.y];
      setLassoPath([start]);
      startGesture(event, { type: 'lasso', start: point, points: [start], moved: false });
      return;
    }
    if (isSelect) {
      const inUnion =
        multiSelect &&
        unionBounds &&
        point.x >= unionBounds[0] &&
        point.x <= unionBounds[2] &&
        point.y >= unionBounds[1] &&
        point.y <= unionBounds[3];
      if (multiSelect && inUnion) {
        startGesture(event, { type: 'group-move', start: point, items: pageSelection, moved: false });
        return;
      }
      const hit = pickShape(shapes, point.x, point.y, PICK_PX * ppx);
      if (hit) {
        const already = pageSelection.some((item) => item.kind === 'shape' && item.id === hit.id);
        if (multiSelect && already) {
          startGesture(event, { type: 'group-move', start: point, items: pageSelection, moved: false });
          return;
        }
        controller.select({ pageIndex, id: hit.id, kind: 'shape' });
        startGesture(event, { type: 'move', start: point, shape: hit, moved: false });
        return;
      }
      const inkHit = pickInk(inks, point.x, point.y, PICK_PX * ppx);
      if (inkHit) {
        const already = pageSelection.some((item) => item.kind === 'ink' && item.id === inkHit.id);
        if (multiSelect && already) {
          startGesture(event, { type: 'group-move', start: point, items: pageSelection, moved: false });
          return;
        }
        controller.select({ pageIndex, id: inkHit.id, kind: 'ink' });
        startGesture(event, { type: 'ink-move', start: point, ink: inkHit, moved: false });
        return;
      }
      controller.select(null);
      return;
    }
    if (isPointKind(tool) && !['line', 'arrow'].includes(tool)) {
      const current = polyRef.current;
      if (current) {
        const first = current.points[0];
        const last = current.points[current.points.length - 1];
        const nearFirst = CLOSED_KINDS.includes(tool) && current.points.length >= 3 && Math.hypot(point.x - first[0], point.y - first[1]) <= 8 * ppx;
        if (nearFirst) {
          finishPoly();
          return;
        }
        if (Math.hypot(point.x - last[0], point.y - last[1]) <= 1.5 * ppx) return; // 두 번 누르기의 둘째 누름
        setPoly({ points: [...current.points, [point.x, point.y]], hover: [point.x, point.y] });
      } else {
        setPoly({ points: [[point.x, point.y]], hover: [point.x, point.y] });
      }
      return;
    }
    startGesture(event, { type: 'create', start: point, kind: tool, moved: false });
  }

  function onDoubleClick(event) {
    if (isSelect) {
      const point = toPt(event);
      const hit = pickShape(shapes, point.x, point.y, PICK_PX * pxToPt());
      if (hit && hit.kind === 'text') {
        controller.select({ pageIndex, id: hit.id, kind: 'shape' });
        controller.beginText({ pageIndex, id: hit.id, rect: hit.rect, params: hit.params, text: hit.params.text || '' });
      }
      return;
    }
    if (polyRef.current && !['line', 'arrow'].includes(tool)) {
      event.preventDefault();
      finishPoly();
    }
  }

  function onPointerMove(event) {
    const gesture = gestureRef.current;
    const point = toPt(event);
    if (!gesture) {
      if (polyRef.current) setPoly((prev) => (prev ? { ...prev, hover: [point.x, point.y] } : prev));
      else if (isSelect) {
        const hit = pickShape(shapes, point.x, point.y, PICK_PX * pxToPt());
        const inkHit = hit ? null : pickInk(inks, point.x, point.y, PICK_PX * pxToPt());
        const next = hit ? hit.id : inkHit ? inkHit.id : null;
        if (next !== hoverId) setHoverId(next);
      }
      return;
    }
    if (gesture.pointerId !== event.pointerId) return;
    const ppx = pxToPt();
    if (!gesture.moved && Math.hypot(point.x - gesture.start.x, point.y - gesture.start.y) < CLICK_PX * ppx) return;
    gesture.moved = true;
    gesture.last = point;
    if (gesture.type === 'lasso') {
      const pts = gesture.points;
      const last = pts[pts.length - 1];
      if (Math.hypot(point.x - last[0], point.y - last[1]) >= 1.5 * ppx) {
        pts.push([point.x, point.y]);
        setLassoPath(pts.slice());
      }
    } else if (gesture.type === 'group-move') {
      const bounds = selectionBounds(gesture.items, inks, shapes) || [0, 0, 0, 0];
      const [dx, dy] = clampDelta(bounds, point.x - gesture.start.x, point.y - gesture.start.y, ptW, ptH);
      setGhost({ group: { dx, dy, items: gesture.items }, moving: true });
    } else if (gesture.type === 'move') {
      const geom = moveGeom(gesture.shape, point.x - gesture.start.x, point.y - gesture.start.y, ptW, ptH);
      setGhost({ shape: withGeom(gesture.shape, geom), moving: true });
    } else if (gesture.type === 'resize') {
      setGhost({ shape: withGeom(gesture.shape, dragHandle(gesture.shape, gesture.handleId, point.x, point.y, ptW, ptH)), moving: true });
    } else if (gesture.type === 'ink-move') {
      const geom = moveInk(gesture.ink, point.x - gesture.start.x, point.y - gesture.start.y, ptW, ptH);
      setGhost({ ink: withInkStrokes(gesture.ink, geom.strokes), moving: true });
    } else if (gesture.type === 'ink-resize') {
      const geom = scaleInk(gesture.ink, gesture.handleId, point.x, point.y, ptW, ptH);
      setGhost({ ink: withInkStrokes(gesture.ink, geom.strokes), moving: true });
    } else if (gesture.type === 'create') {
      const geom = createGeom(gesture.kind, gesture.start, point, event.shiftKey);
      setGhost({ shape: draftShape(gesture.kind, geom, newParams), moving: false });
    }
  }

  function createGeom(kind, start, point, shift) {
    if (kind === 'line' || kind === 'arrow') {
      const end = shift ? clampPoint(snapAngle(start, point), ptW, ptH) : point;
      return { points: [[start.x, start.y], [end.x, end.y]] };
    }
    return { rect: rectFromDrag(start, point, shift && kind !== 'text') };
  }

  function endGesture(event, cancelled) {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    gestureRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    const ppx = pxToPt();
    const point = toPt(event);
    if (cancelled) {
      setGhost(null);
      setLassoPath(null);
      return;
    }
    if (gesture.type === 'lasso') {
      const pts = gesture.points.length >= 2 ? gesture.points : [[gesture.start.x, gesture.start.y], [point.x, point.y]];
      setLassoPath(null);
      if (!gesture.moved && pts.length < 3) {
        controller.select(null);
        return;
      }
      const hits = pickLassoHits(inks, shapes, pageIndex, pts, PICK_PX * ppx);
      controller.selectMany(hits);
      return;
    }
    if (gesture.type === 'group-move') {
      if (!gesture.moved) {
        setGhost(null);
        return;
      }
      const bounds = selectionBounds(gesture.items, inks, shapes) || [0, 0, 0, 0];
      const [dx, dy] = clampDelta(bounds, point.x - gesture.start.x, point.y - gesture.start.y, ptW, ptH);
      setGhost(null);
      if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01) return;
      void controller.moveSelection(dx, dy, ptW, ptH, gesture.items);
      return;
    }
    if (gesture.type === 'create') {
      setGhost(null);
      const { kind } = gesture;
      if (kind === 'text') {
        let rect;
        if (gesture.moved) rect = rectFromDrag(gesture.start, point);
        else {
          const x0 = Math.min(gesture.start.x, Math.max(0, ptW - DEFAULT_TEXT_BOX[0]));
          const y0 = Math.min(gesture.start.y, Math.max(0, ptH - DEFAULT_TEXT_BOX[1]));
          rect = [x0, y0, x0 + DEFAULT_TEXT_BOX[0], y0 + DEFAULT_TEXT_BOX[1]];
        }
        if (rect[2] - rect[0] < 20 * ppx || rect[3] - rect[1] < 10 * ppx) return;
        controller.beginText({ pageIndex, id: null, rect, params: { ...newParams, kind: 'text' }, text: '' });
        return;
      }
      if (!gesture.moved) return;
      const geom = createGeom(kind, gesture.start, point, event.shiftKey);
      const tiny = geom.rect ? geom.rect[2] - geom.rect[0] < MIN_BOX || geom.rect[3] - geom.rect[1] < MIN_BOX : Math.hypot(geom.points[1][0] - geom.points[0][0], geom.points[1][1] - geom.points[0][1]) < MIN_BOX;
      if (tiny) return;
      setGhost({ shape: draftShape(kind, geom, newParams), moving: false });
      void controller.create(pageIndex, kind, geom, newParams).finally(() => setGhost(null));
      return;
    }
    // move / resize (shape or ink)
    if (!gesture.moved) {
      setGhost(null);
      return;
    }
    if (gesture.type === 'ink-move' || gesture.type === 'ink-resize') {
      const geom =
        gesture.type === 'ink-move'
          ? moveInk(gesture.ink, point.x - gesture.start.x, point.y - gesture.start.y, ptW, ptH)
          : scaleInk(gesture.ink, gesture.handleId, point.x, point.y, ptW, ptH);
      if (sameInkStrokes(geom.strokes, gesture.ink.strokes)) {
        setGhost(null);
        return;
      }
      setGhost({ ink: withInkStrokes(gesture.ink, geom.strokes), moving: true });
      void controller.updateInk(pageIndex, gesture.ink.id, geom.strokes).finally(() => setGhost(null));
      return;
    }
    const geom =
      gesture.type === 'move'
        ? moveGeom(gesture.shape, point.x - gesture.start.x, point.y - gesture.start.y, ptW, ptH)
        : dragHandle(gesture.shape, gesture.handleId, point.x, point.y, ptW, ptH);
    if (sameGeom(geom, geomOf(gesture.shape))) {
      setGhost(null);
      return;
    }
    setGhost({ shape: withGeom(gesture.shape, geom), moving: true });
    void controller.update(pageIndex, gesture.shape.id, { geom }).finally(() => setGhost(null));
  }

  function onHandleDown(event, handle) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (gestureRef.current || !selected) return;
    event.preventDefault();
    event.stopPropagation();
    // 이벤트가 레이어로 올라가지 않으므로, 레이어 쪽에서 끌기를 이어 받게 포인터를 레이어에 붙잡는다.
    layerRef.current.setPointerCapture?.(event.pointerId);
    gestureRef.current = { pointerId: event.pointerId, type: 'resize', handleId: handle.id, shape: selected, start: toPt(event), moved: false };
  }

  function onInkHandleDown(event, handle) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (gestureRef.current || !selectedInk) return;
    event.preventDefault();
    event.stopPropagation();
    layerRef.current.setPointerCapture?.(event.pointerId);
    gestureRef.current = {
      pointerId: event.pointerId,
      type: 'ink-resize',
      handleId: handle.id,
      ink: selectedInk,
      start: toPt(event),
      moved: false,
    };
  }

  // ---- 그리기
  const px = unit; // 화면 px → pt
  const handles = isSelect && selected && !editing && !ghost ? shapeHandles(selected) : [];
  const bounds = isSelect && selected && !editing && !ghost ? shapeBounds(selected) : null;
  const ghostInk = ghost?.ink || null;
  const showInkSelection = isSelect && selectedInk && !ghost;
  const inkBox = showInkSelection ? inkBounds(selectedInk) : ghostInk ? inkBounds(ghostInk) : null;
  const inkHandleList = showInkSelection ? inkHandles(selectedInk) : [];
  const pad = selected ? Math.max(0, selected.params.width || 0) / 2 + 3 * px : 0;
  const inkPad = selectedInk || ghostInk ? Math.max(0, Number((ghostInk || selectedInk).width) || 0) / 2 + 3 * px : 0;

  let polyShape = null;
  if (poly && poly.points.length) {
    const pts = poly.hover ? [...poly.points, poly.hover] : poly.points;
    polyShape = draftShape(tool, { points: pts.length >= 2 ? pts : [...pts, pts[0]] }, newParams);
  }

  const groupGhost = ghost?.group || null;
  const groupGhostBounds =
    groupGhost && unionBounds
      ? [
          unionBounds[0] + groupGhost.dx,
          unionBounds[1] + groupGhost.dy,
          unionBounds[2] + groupGhost.dx,
          unionBounds[3] + groupGhost.dy,
        ]
      : null;
  const multiBox = !ghost && multiSelect ? unionBounds : groupGhostBounds;
  const cursor = isLasso
    ? 'crosshair'
    : isSelect
      ? hoverId != null || multiSelect
        ? 'move'
        : 'default'
      : tool === 'text'
        ? 'text'
        : 'crosshair';

  return (
    <div
      ref={layerRef}
      data-shape-layer="1"
      data-shape-tool={tool}
      className="absolute inset-0 z-20 select-none"
      style={{ touchAction: 'none', cursor }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={(event) => endGesture(event, false)}
      onPointerCancel={(event) => endGesture(event, true)}
      onPointerLeave={() => {
        if (hoverId != null && !gestureRef.current) setHoverId(null);
      }}
      onDoubleClick={onDoubleClick}
      onContextMenu={(event) => event.preventDefault()}
    >
      <svg viewBox={`0 0 ${ptW} ${ptH}`} className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" data-shape-svg="1">
        {ghost?.shape ? (
          <g data-shape-ghost="1">
            <ShapePreview shape={ghost.shape} />
            {ghost.moving ? (
              <rect
                x={shapeBounds(ghost.shape)[0] - pad}
                y={shapeBounds(ghost.shape)[1] - pad}
                width={shapeBounds(ghost.shape)[2] - shapeBounds(ghost.shape)[0] + pad * 2}
                height={shapeBounds(ghost.shape)[3] - shapeBounds(ghost.shape)[1] + pad * 2}
                className="stroke-app-accent"
                fill="none"
                strokeWidth={1}
                strokeDasharray="4 3"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </g>
        ) : null}
        {ghostInk ? (
          <g data-ink-ghost="1">
            <InkPreview ink={ghostInk} />
            {ghost?.moving && inkBox ? (
              <rect
                x={inkBox[0] - inkPad}
                y={inkBox[1] - inkPad}
                width={inkBox[2] - inkBox[0] + inkPad * 2}
                height={inkBox[3] - inkBox[1] + inkPad * 2}
                className="stroke-app-accent"
                fill="none"
                strokeWidth={1}
                strokeDasharray="4 3"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </g>
        ) : null}
        {polyShape ? (
          <g data-shape-poly="1">
            <ShapePreview shape={polyShape} />
            {CLOSED_KINDS.includes(tool) && poly.points.length >= 3 ? (
              <circle cx={poly.points[0][0]} cy={poly.points[0][1]} r={5 * px} className="fill-white stroke-app-accent" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            ) : null}
          </g>
        ) : null}
        {lassoPath && lassoPath.length ? (
          <g data-lasso-path="1">
            <polyline
              points={lassoPath.map((p) => `${p[0]},${p[1]}`).join(' ')}
              fill="none"
              className="stroke-app-accent"
              strokeWidth={1.25}
              strokeDasharray="5 3"
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
            {lassoPath.length >= 3 ? (
              <line
                x1={lassoPath[lassoPath.length - 1][0]}
                y1={lassoPath[lassoPath.length - 1][1]}
                x2={lassoPath[0][0]}
                y2={lassoPath[0][1]}
                className="stroke-app-accent"
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.7}
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </g>
        ) : null}
        {multiBox ? (
          <g data-multi-selection="1">
            <rect
              x={multiBox[0] - 3 * px}
              y={multiBox[1] - 3 * px}
              width={multiBox[2] - multiBox[0] + 6 * px}
              height={multiBox[3] - multiBox[1] + 6 * px}
              className="stroke-app-accent"
              fill="rgba(71, 85, 105, 0.06)"
              strokeWidth={1}
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
            />
          </g>
        ) : null}
        {showInkSelection && inkBox ? (
          <g data-ink-selection="1">
            <rect
              x={inkBox[0] - inkPad}
              y={inkBox[1] - inkPad}
              width={inkBox[2] - inkBox[0] + inkPad * 2}
              height={inkBox[3] - inkBox[1] + inkPad * 2}
              className="stroke-app-accent"
              fill="none"
              strokeWidth={1}
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
            />
            {inkHandleList.map((handle) => (
              <rect
                key={handle.id}
                data-ink-handle={handle.id}
                x={handle.x - (HANDLE_PX / 2) * px}
                y={handle.y - (HANDLE_PX / 2) * px}
                width={HANDLE_PX * px}
                height={HANDLE_PX * px}
                rx={px}
                className="fill-white stroke-app-accent"
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
                style={{ pointerEvents: 'all', cursor: inkHandleCursor(handle.id) }}
                onPointerDown={(event) => onInkHandleDown(event, handle)}
              />
            ))}
          </g>
        ) : null}
        {bounds ? (
          <g data-shape-selection="1">
            <rect
              x={bounds[0] - pad}
              y={bounds[1] - pad}
              width={bounds[2] - bounds[0] + pad * 2}
              height={bounds[3] - bounds[1] + pad * 2}
              className="stroke-app-accent"
              fill="none"
              strokeWidth={1}
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
            />
            {handles.map((handle) => (
              <rect
                key={handle.id}
                data-shape-handle={handle.id}
                x={handle.x - (HANDLE_PX / 2) * px}
                y={handle.y - (HANDLE_PX / 2) * px}
                width={HANDLE_PX * px}
                height={HANDLE_PX * px}
                rx={handle.id.startsWith('p') ? (HANDLE_PX / 2) * px : px}
                className="fill-white stroke-app-accent"
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
                style={{ pointerEvents: 'all', cursor: handleCursor(handle.id) }}
                onPointerDown={(event) => onHandleDown(event, handle)}
              />
            ))}
          </g>
        ) : null}
      </svg>
      {editing ? <TextEditor editing={editing} ptW={ptW} ptH={ptH} unit={unit} controller={controller} /> : null}
    </div>
  );
}

function TextEditor({ editing, ptW, ptH, unit, controller }) {
  const ref = useRef(null);
  const [x0, y0, x1, y1] = editing.rect;
  const params = editing.params;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);
  const fontPx = (params.fontSize || 14) / unit;
  return (
    <textarea
      ref={ref}
      data-shape-text="1"
      value={editing.text}
      spellCheck={false}
      placeholder="글을 입력하세요"
      onChange={(event) => controller.setTextValue(event.target.value)}
      onBlur={() => void controller.commitText()}
      onPointerDown={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === 'Escape' || (event.key === 'Enter' && (event.ctrlKey || event.metaKey))) {
          event.preventDefault();
          event.stopPropagation();
          void controller.commitText();
        }
      }}
      className="absolute resize-none overflow-hidden outline outline-2 outline-app-accent"
      style={{
        left: `${(x0 / ptW) * 100}%`,
        top: `${(y0 / ptH) * 100}%`,
        width: `${((x1 - x0) / ptW) * 100}%`,
        height: `${((y1 - y0) / ptH) * 100}%`,
        fontSize: `${fontPx}px`,
        lineHeight: 1.2,
        // 엔진은 글을 (여백 4pt + 테두리 굵기 × 2) 안쪽에서 시작한다. 입력창 테두리가 굵기만큼 차지하므로 나머지만 여백으로 둔다.
        padding: `${(4 + (params.width || 0)) / unit}px`,
        color: params.textColor || '#000',
        background: params.fill || '#ffffff',
        border: params.width > 0 ? `${params.width / unit}px solid ${params.color}` : 'none',
        boxSizing: 'border-box',
        fontFamily: 'sans-serif',
        textAlign: ['left', 'center', 'right'][params.align || 0],
      }}
    />
  );
}
