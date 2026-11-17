import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { HANDLES, handlePoint, imageAspect, moveRect, resizeRect, styleFromRect } from './imageBoxMath.js';

const HANDLE_SIZE = 9;
const HANDLE_HIT_MAX = 14;
const HANDLE_HIT_MIN = 6;
const HANDLE_CURSOR = {
  nw: 'nwse-resize',
  se: 'nwse-resize',
  ne: 'nesw-resize',
  sw: 'nesw-resize',
  n: 'ns-resize',
  s: 'ns-resize',
  e: 'ew-resize',
  w: 'ew-resize',
};

function handleBox(name) {
  const s = HANDLE_SIZE;
  const half = s / 2;
  const map = {
    nw: { left: -half, top: -half },
    n: { left: `calc(50% - ${half}px)`, top: -half },
    ne: { right: -half, top: -half },
    e: { right: -half, top: `calc(50% - ${half}px)` },
    se: { right: -half, bottom: -half },
    s: { left: `calc(50% - ${half}px)`, bottom: -half },
    sw: { left: -half, bottom: -half },
    w: { left: -half, top: `calc(50% - ${half}px)` },
  };
  return {
    position: 'absolute',
    width: s,
    height: s,
    background: '#fff',
    border: '1px solid #2563eb',
    boxSizing: 'border-box',
    cursor: HANDLE_CURSOR[name],
    ...map[name],
  };
}

/**
 * 이미지 넣기 오버레이. 미리보기 크기가 곧 PDF 확정 크기(WYSIWYG).
 * 드래그=이동, 핸들=크기(비율 유지, 잡은 핸들이 커서를 따라옴), Enter/더블클릭/바깥 클릭=확정, Esc=취소, Delete=버리기.
 * 상자 위치·크기는 imageBoxMath 의 rect(pt) 하나만 쓰고, 화면용 보정은 하지 않는다.
 */
export default function ImagePlaceOverlay({
  image,
  mime = 'image/png',
  rect,
  page,
  imageWidth,
  imageHeight,
  onChangeRect,
  onCommit,
  onCancel,
  onDelete,
  onDraggingChange,
}) {
  const rootRef = useRef(null);
  const dragRef = useRef(null);
  const liveRectRef = useRef(rect);
  const [liveRect, setLiveRect] = useState(rect);
  const [px0, py0, pw, ph] = page;
  const aspect = imageAspect(imageWidth, imageHeight);

  useLayoutEffect(() => {
    if (dragRef.current) return;
    liveRectRef.current = rect;
    setLiveRect(rect);
  }, [rect]);

  useEffect(() => {
    rootRef.current?.focus();
  }, []);

  function pagePointFromClient(clientX, clientY) {
    const host = rootRef.current?.offsetParent;
    if (!host) return { x: liveRectRef.current[0], y: liveRectRef.current[1] };
    const box = host.getBoundingClientRect();
    return {
      x: px0 + ((clientX - box.left) / Math.max(1, box.width)) * pw,
      y: py0 + ((clientY - box.top) / Math.max(1, box.height)) * ph,
    };
  }

  /** 안쪽은 이동, 가장자리/바깥 핸들만 크기 조절. 작은 상자에서 핸들에 전부 먹히지 않게 반경을 줄인다. */
  function hitHandle(localX, localY, widthPx, heightPx) {
    const points = {
      nw: [0, 0],
      n: [widthPx / 2, 0],
      ne: [widthPx, 0],
      e: [widthPx, heightPx / 2],
      se: [widthPx, heightPx],
      s: [widthPx / 2, heightPx],
      sw: [0, heightPx],
      w: [0, heightPx / 2],
    };
    const reach = Math.min(HANDLE_HIT_MAX, Math.max(HANDLE_HIT_MIN, Math.min(widthPx, heightPx) * 0.3));
    let best = null;
    let bestDist = reach;
    for (const name of HANDLES) {
      const [hx, hy] = points[name];
      const dist = Math.hypot(localX - hx, localY - hy);
      if (dist <= bestDist) {
        best = name;
        bestDist = dist;
      }
    }
    return best;
  }

  function applyLive(next) {
    liveRectRef.current = next;
    setLiveRect(next);
    onChangeRect(next);
  }

  function endDrag(event) {
    if (!dragRef.current) return;
    dragRef.current = null;
    onDraggingChange?.(false);
    try {
      rootRef.current?.releasePointerCapture(event.pointerId);
    } catch {
      // ignore
    }
  }

  function localPoint(event) {
    const el = rootRef.current;
    const box = el.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top, w: box.width, h: box.height };
  }

  function onPointerDown(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const el = rootRef.current;
    const local = localPoint(event);
    const handle = hitHandle(local.x, local.y, local.w, local.h) || 'move';
    const point = pagePointFromClient(event.clientX, event.clientY);
    const origin = [...liveRectRef.current];
    // 핸들을 잡은 자리와 핸들 중심의 차이. 이걸 빼 줘야 잡는 순간 상자가 튀지 않고 핸들이 커서에 붙어 따라온다.
    const anchor = handle === 'move' ? null : handlePoint(origin, handle);
    const grab = anchor ? { x: point.x - anchor[0], y: point.y - anchor[1] } : null;
    dragRef.current = { handle, origin, point, grab };
    onDraggingChange?.(true);
    el.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event) {
    const drag = dragRef.current;
    if (!drag) {
      const el = rootRef.current;
      if (!el) return;
      const local = localPoint(event);
      const handle = hitHandle(local.x, local.y, local.w, local.h);
      el.style.cursor = handle ? HANDLE_CURSOR[handle] : 'move';
      return;
    }
    const point = pagePointFromClient(event.clientX, event.clientY);
    if (drag.handle === 'move') {
      applyLive(moveRect(drag.origin, point.x - drag.point.x, point.y - drag.point.y, page));
    } else {
      applyLive(resizeRect(drag.origin, drag.handle, point, aspect, page, drag.grab));
    }
  }

  function onKeyDown(event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      onCommit();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      onCancel();
    } else if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      onDelete();
    }
  }

  const box = styleFromRect(liveRect, page);

  return (
    <div
      ref={rootRef}
      tabIndex={0}
      role="button"
      aria-label="이미지 편집"
      data-img-overlay="1"
      className="absolute z-20 outline-none"
      style={{
        ...box,
        cursor: 'move',
        outline: '1px dashed #2563eb',
        outlineOffset: 0,
        boxSizing: 'border-box',
        touchAction: 'none',
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onCommit();
      }}
      onKeyDown={onKeyDown}
      onContextMenu={(event) => event.preventDefault()}
    >
      <img
        src={`data:${mime};base64,${image}`}
        alt=""
        draggable={false}
        className="pointer-events-none block h-full w-full select-none"
        style={{ objectFit: 'fill' }}
      />
      {HANDLES.map((name) => (
        <span key={name} aria-hidden style={handleBox(name)} />
      ))}
    </div>
  );
}
