import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { finalizeStroke, tracePath } from './strokeMath.js';

/**
 * 쪽 이미지 위에 겹치는 그리기 레이어.
 *
 * - 좌표는 PDF 쪽 좌표(pt, 회전 반영 화면 기준)로 다룬다. 배율이 바뀌어도 획이 제 자리에 남는다.
 * - 손을 떼면 획을 다듬어 부모(onStroke)에게 넘긴다. 엔진이 PDF 에 반영하고 쪽 그림이 새로 올 때까지는
 *   이 레이어의 캔버스가 획을 계속 보여 준다(깜빡임 방지). 반영이 끝나면(성공이든 실패든) 지운다.
 * - 캔버스는 그리는 중이거나 반영을 기다리는 획이 있을 때만 만든다. 쪽이 많아도 메모리를 쓰지 않는다.
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

export default function DrawLayer({ pageIndex, ptW, ptH, tool, settings, onStroke }) {
  const layerRef = useRef(null);
  const canvasRef = useRef(null);
  const liveRef = useRef(/** @type {null | { pointerId: number, points: {x:number,y:number}[], style: any, startedAt: number }} */ (null));
  const pendingRef = useRef(/** @type {any[]} */ ([]));
  const rafRef = useRef(0);
  const [canvasOn, setCanvasOn] = useState(false);

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
    ctx.setTransform((pxW / ptW), 0, 0, (pxH / ptH), 0, 0);
    for (const stroke of pendingRef.current) paintStroke(ctx, stroke);
    const live = liveRef.current;
    if (live) paintStroke(ctx, { ...live.style, points: live.points });
  }, [ptW, ptH]);

  const scheduleRedraw = useCallback(() => {
    if (!rafRef.current) rafRef.current = requestAnimationFrame(redraw);
  }, [redraw]);

  // 배율이 바뀌면 같은 획을 새 크기로 다시 그린다.
  useLayoutEffect(() => {
    if (canvasOn) redraw();
  }, [canvasOn, redraw, ptW, ptH]);

  useEffect(
    () => () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  // 도구가 바뀌거나 모드가 꺼지면 그리던 획은 버린다. (반영을 기다리는 획은 부모가 계속 처리한다.)
  useEffect(() => {
    liveRef.current = null;
  }, [tool]);

  function dropPending(stroke) {
    pendingRef.current = pendingRef.current.filter((item) => item !== stroke);
    if (!pendingRef.current.length && !liveRef.current) setCanvasOn(false);
    else scheduleRedraw();
  }

  function onPointerDown(event) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (liveRef.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const style = {
      color: settings.color,
      width: settings.thickness,
      opacity: settings.opacity / 100,
    };
    liveRef.current = { pointerId: event.pointerId, points: [toPt(event)], style, startedAt: Date.now() };
    setCanvasOn(true);
    scheduleRedraw();
  }

  function onPointerMove(event) {
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

  function finishStroke(event, cancelled) {
    const live = liveRef.current;
    if (!live || live.pointerId !== event.pointerId) return;
    liveRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    if (cancelled) {
      if (!pendingRef.current.length) setCanvasOn(false);
      else scheduleRedraw();
      return;
    }
    const final = finalizeStroke(live.points, live.style.width);
    if (!final.length) {
      if (!pendingRef.current.length) setCanvasOn(false);
      return;
    }
    const stroke = { ...live.style, points: final.map(([x, y]) => ({ x, y })) };
    pendingRef.current.push(stroke);
    scheduleRedraw();
    const timing = { startedAt: live.startedAt, endedAt: Date.now() };
    const finished = Promise.resolve(onStroke(pageIndex, final, live.style, timing)).catch(() => {});
    // 쪽 그림이 바뀐 뒤에 지워야 획이 잠깐 사라지는 일이 없다.
    void finished.then(
      () =>
        new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => window.setTimeout(resolve, 40)));
        }),
    ).then(() => dropPending(stroke));
  }

  return (
    <div
      ref={layerRef}
      data-draw-layer="1"
      className="absolute inset-0 z-20 select-none"
      style={{ touchAction: 'none', cursor: 'crosshair' }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={(event) => finishStroke(event, false)}
      onPointerCancel={(event) => finishStroke(event, true)}
      onContextMenu={(event) => event.preventDefault()}
    >
      {canvasOn ? <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" /> : null}
    </div>
  );
}
