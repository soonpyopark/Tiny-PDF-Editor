import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { finalizeStroke, tracePath } from './strokeMath.js';

/**
 * 쪽 이미지 위에 겹치는 그리기 레이어.
 *
 * - 좌표는 PDF 쪽 좌표(pt, 회전 반영 화면 기준)로 다룬다. 배율이 바뀌어도 획이 제 자리에 남는다.
 * - 그리기: 손을 떼면 획을 다듬어 부모(onStroke)에게 넘긴다. 엔진이 PDF 에 반영하고 쪽 그림이 새로 올 때까지는
 *   이 레이어의 캔버스가 획을 계속 보여 준다(깜빡임 방지). 반영이 끝나면(성공이든 실패든) 지운다.
 * - 지우개: 누른 채 움직이는 경로를 조각내 부모(onErase)에게 넘긴다. 이 앱이 그린 획 중 경로에 닿은 것만 지워진다.
 *   요청은 한 번에 하나씩 보내고, 기다리는 동안 쌓인 경로는 다음 요청에 합친다.
 * - 캔버스는 그리는 중이거나 반영을 기다리는 획·지우개 원이 있을 때만 만든다. 쪽이 많아도 메모리를 쓰지 않는다.
 */

function paintStroke(ctx, stroke) {
  ctx.save();
  ctx.globalAlpha = stroke.opacity;
  ctx.strokeStyle = stroke.color;
  ctx.lineWidth = stroke.width;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  tracePath(ctx, stroke.points);
  ctx.stroke();
  ctx.restore();
}

function paintEraserRing(ctx, center, radius, unit) {
  ctx.save();
  ctx.lineWidth = 1.25 * unit;
  ctx.fillStyle = 'rgba(148, 163, 184, 0.18)';
  ctx.strokeStyle = 'rgba(71, 85, 105, 0.9)';
  ctx.beginPath();
  ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

let dragCounter = 0;

export default function DrawLayer({ pageIndex, ptW, ptH, tool, settings, onStroke, onErase }) {
  const layerRef = useRef(null);
  const canvasRef = useRef(null);
  const liveRef = useRef(/** @type {null | { pointerId: number, points: {x:number,y:number}[], style: any, startedAt: number }} */ (null));
  const eraseRef = useRef(
    /** @type {null | { pointerId: number, dragId: number, startedAt: number, sent: {x:number,y:number} | null, queue: {x:number,y:number}[], sending: boolean, done: boolean }} */ (null),
  );
  const hoverRef = useRef(/** @type {null | {x:number,y:number}} */ (null));
  const pendingRef = useRef(/** @type {any[]} */ ([]));
  const rafRef = useRef(0);
  const [canvasOn, setCanvasOn] = useState(false);
  const isEraser = tool === 'eraser';
  const radius = isEraser ? settings.radius : 0;
  const radiusRef = useRef(radius);
  radiusRef.current = radius;

  const toPt = useCallback(
    (event) => {
      const rect = layerRef.current.getBoundingClientRect();
      return {
        x: ((event.clientX - rect.left) / rect.width) * ptW,
        y: ((event.clientY - rect.top) / rect.height) * ptH,
      };
    },
    [ptW, ptH],
  );

  const redraw = useCallback(() => {
    rafRef.current = 0;
    const canvas = canvasRef.current;
    const layer = layerRef.current;
    if (!canvas || !layer) return;
    const rect = layer.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const pxW = Math.max(1, Math.round(rect.width * dpr));
    const pxH = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== pxW) canvas.width = pxW;
    if (canvas.height !== pxH) canvas.height = pxH;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    // pt 좌표를 그대로 그릴 수 있게 변환을 건다.
    ctx.setTransform(pxW / ptW, 0, 0, pxH / ptH, 0, 0);
    for (const stroke of pendingRef.current) paintStroke(ctx, stroke);
    const live = liveRef.current;
    if (live) paintStroke(ctx, { ...live.style, points: live.points });
    if (hoverRef.current && radiusRef.current > 0) {
      paintEraserRing(ctx, hoverRef.current, radiusRef.current, ptW / rect.width);
    }
  }, [ptW, ptH]);

  const scheduleRedraw = useCallback(() => {
    if (!rafRef.current) rafRef.current = requestAnimationFrame(redraw);
  }, [redraw]);

  const needsCanvas = useCallback(
    () => Boolean(pendingRef.current.length || liveRef.current || hoverRef.current),
    [],
  );

  const refreshCanvasState = useCallback(() => {
    if (needsCanvas()) {
      setCanvasOn(true);
      scheduleRedraw();
    } else {
      setCanvasOn(false);
    }
  }, [needsCanvas, scheduleRedraw]);

  // 배율이 바뀌면 같은 획을 새 크기로 다시 그린다.
  useLayoutEffect(() => {
    if (canvasOn) redraw();
  }, [canvasOn, redraw, ptW, ptH, radius]);

  useEffect(
    () => () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  // 도구가 바뀌면 그리던 획·지우개 원은 버린다. (반영을 기다리는 획은 부모가 계속 처리한다.)
  useEffect(() => {
    liveRef.current = null;
    eraseRef.current = null;
    hoverRef.current = null;
    refreshCanvasState();
    // 도구가 바뀔 때만 실행한다. (콜백 정체성이 바뀐다고 그리던 획을 버리면 안 된다.)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool]);

  function dropPending(stroke) {
    pendingRef.current = pendingRef.current.filter((item) => item !== stroke);
    refreshCanvasState();
  }

  // ---- 지우개
  function pumpErase() {
    const drag = eraseRef.current;
    if (!drag || drag.sending) return;
    if (!drag.queue.length) {
      if (drag.done && eraseRef.current === drag) eraseRef.current = null;
      return;
    }
    // 이전 요청의 마지막 점에서 이어서 보낸다 (조각 사이 틈이 없게).
    const chunk = drag.sent ? [drag.sent, ...drag.queue] : drag.queue.slice();
    drag.sent = drag.queue[drag.queue.length - 1];
    drag.queue = [];
    drag.sending = true;
    const meta = { dragId: drag.dragId, startedAt: drag.startedAt, endedAt: Date.now() };
    Promise.resolve(onErase(pageIndex, chunk.map((p) => [p.x, p.y]), radiusRef.current, meta))
      .catch(() => {})
      .finally(() => {
        drag.sending = false;
        pumpErase();
      });
  }

  function onPointerDown(event) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (liveRef.current || eraseRef.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = toPt(event);
    if (isEraser) {
      dragCounter += 1;
      eraseRef.current = {
        pointerId: event.pointerId,
        dragId: dragCounter,
        startedAt: Date.now(),
        sent: null,
        queue: [point],
        sending: false,
        done: false,
      };
      hoverRef.current = point;
      refreshCanvasState();
      pumpErase();
      return;
    }
    const style = {
      color: settings.color,
      width: settings.thickness,
      opacity: settings.opacity / 100,
    };
    liveRef.current = { pointerId: event.pointerId, points: [point], style, startedAt: Date.now() };
    refreshCanvasState();
  }

  function onPointerMove(event) {
    const drag = eraseRef.current;
    if (isEraser) {
      const point = toPt(event);
      hoverRef.current = point;
      if (drag && drag.pointerId === event.pointerId) {
        const events = typeof event.nativeEvent.getCoalescedEvents === 'function' ? event.nativeEvent.getCoalescedEvents() : [];
        for (const item of events.length ? events : [event.nativeEvent]) drag.queue.push(toPt(item));
        pumpErase();
      }
      refreshCanvasState();
      return;
    }
    const live = liveRef.current;
    if (!live || live.pointerId !== event.pointerId) return;
    const events = typeof event.nativeEvent.getCoalescedEvents === 'function' ? event.nativeEvent.getCoalescedEvents() : [];
    for (const item of events.length ? events : [event.nativeEvent]) {
      const point = toPt(item);
      const last = live.points[live.points.length - 1];
      if (Math.hypot(point.x - last.x, point.y - last.y) >= 0.3) live.points.push(point);
    }
    scheduleRedraw();
  }

  function onPointerLeave() {
    if (!isEraser || eraseRef.current) return;
    hoverRef.current = null;
    refreshCanvasState();
  }

  function finishStroke(event, cancelled) {
    const drag = eraseRef.current;
    if (drag && drag.pointerId === event.pointerId) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      if (!cancelled) drag.queue.push(toPt(event));
      drag.done = true;
      pumpErase();
      return;
    }
    const live = liveRef.current;
    if (!live || live.pointerId !== event.pointerId) return;
    liveRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    if (cancelled) {
      refreshCanvasState();
      return;
    }
    const final = finalizeStroke(live.points, live.style.width);
    if (!final.length) {
      refreshCanvasState();
      return;
    }
    const stroke = { ...live.style, points: final.map(([x, y]) => ({ x, y })) };
    pendingRef.current.push(stroke);
    scheduleRedraw();
    const timing = { startedAt: live.startedAt, endedAt: Date.now() };
    const finished = Promise.resolve(onStroke(pageIndex, final, live.style, timing)).catch(() => {});
    // 쪽 그림이 바뀐 뒤에 지워야 획이 잠깐 사라지는 일이 없다.
    void finished
      .then(
        () =>
          new Promise((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(() => window.setTimeout(resolve, 40)));
          }),
      )
      .then(() => dropPending(stroke));
  }

  return (
    <div
      ref={layerRef}
      data-draw-layer="1"
      data-draw-tool-active={tool}
      className="absolute inset-0 z-20 select-none"
      style={{ touchAction: 'none', cursor: 'crosshair' }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      onPointerUp={(event) => finishStroke(event, false)}
      onPointerCancel={(event) => finishStroke(event, true)}
      onContextMenu={(event) => event.preventDefault()}
    >
      {canvasOn ? <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" /> : null}
    </div>
  );
}
