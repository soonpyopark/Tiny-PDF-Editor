import { useEffect, useLayoutEffect, useRef, useState } from 'react';

const HANDLE_SIZE = 9;
const HANDLE_HIT = 14;
const MIN_STAMP = 24;
const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
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

function clampRect(rect, page) {
  const [px0, py0, pw, ph] = page;
  let [x0, y0, x1, y1] = rect;
  let width = Math.max(1, x1 - x0);
  let height = Math.max(1, y1 - y0);
  // 페이지의 90% 를 넘지 않게 해서 한 번에 화면을 덮지 않게 한다.
  const maxW = pw * 0.9;
  const maxH = ph * 0.9;
  if (width > maxW || height > maxH) {
    const scale = Math.min(maxW / width, maxH / height);
    width *= scale;
    height *= scale;
  }
  x0 = Math.min(Math.max(x0, px0), px0 + pw - width);
  y0 = Math.min(Math.max(y0, py0), py0 + ph - height);
  return [x0, y0, x0 + width, y0 + height];
}

function imageAspect(width, height) {
  return Math.max(1, width) / Math.max(1, height);
}

function moveRect(origin, dx, dy, page) {
  return clampRect([origin[0] + dx, origin[1] + dy, origin[2] + dx, origin[3] + dy], page);
}

/**
 * 모서리: 커서의 가로·세로를 모두 반영해 비율을 유지한다.
 * (예전엔 가로만 봐서 세로형 서명이 갑자기 커지거나 거의 안 커졌다.)
 */
function resizeFromCorner(origin, handle, point, aspect, page) {
  const minW = MIN_STAMP;
  const [x0, y0, x1, y1] = origin;
  let fixedX;
  let fixedY;
  let rawW;
  let rawH;
  if (handle === 'se') {
    fixedX = x0;
    fixedY = y0;
    rawW = point.x - fixedX;
    rawH = point.y - fixedY;
  } else if (handle === 'nw') {
    fixedX = x1;
    fixedY = y1;
    rawW = fixedX - point.x;
    rawH = fixedY - point.y;
  } else if (handle === 'ne') {
    fixedX = x0;
    fixedY = y1;
    rawW = point.x - fixedX;
    rawH = fixedY - point.y;
  } else {
    // sw
    fixedX = x1;
    fixedY = y0;
    rawW = fixedX - point.x;
    rawH = point.y - fixedY;
  }
  // 커서가 상자 바깥으로 당긴 쪽에 맞춰 키운다 (둘 중 더 큰 쪽).
  const width = Math.max(minW, Math.abs(rawW), Math.abs(rawH) * aspect);
  const height = width / aspect;
  if (handle === 'se') return clampRect([fixedX, fixedY, fixedX + width, fixedY + height], page);
  if (handle === 'nw') return clampRect([fixedX - width, fixedY - height, fixedX, fixedY], page);
  if (handle === 'ne') return clampRect([fixedX, fixedY - height, fixedX + width, fixedY], page);
  return clampRect([fixedX - width, fixedY, fixedX, fixedY + height], page);
}

/** 변 핸들: 누른 축만으로 크기를 정하고 비율은 유지, 중심은 고정. */
function resizeFromEdge(origin, handle, point, aspect, page) {
  const minW = MIN_STAMP;
  const minH = minW / aspect;
  const [x0, y0, x1, y1] = origin;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  if (handle === 'e' || handle === 'w') {
    const width = Math.max(minW, handle === 'e' ? point.x - x0 : x1 - point.x);
    const height = width / aspect;
    if (handle === 'e') return clampRect([x0, cy - height / 2, x0 + width, cy + height / 2], page);
    return clampRect([x1 - width, cy - height / 2, x1, cy + height / 2], page);
  }
  const height = Math.max(minH, handle === 's' ? point.y - y0 : y1 - point.y);
  const width = height * aspect;
  if (handle === 's') return clampRect([cx - width / 2, y0, cx + width / 2, y0 + height], page);
  return clampRect([cx - width / 2, y1 - height, cx + width / 2, y1], page);
}

function resizeRect(origin, handle, point, imageWidth, imageHeight, page) {
  const aspect = imageAspect(imageWidth, imageHeight);
  if (handle === 'nw' || handle === 'ne' || handle === 'se' || handle === 'sw') {
    return resizeFromCorner(origin, handle, point, aspect, page);
  }
  return resizeFromEdge(origin, handle, point, aspect, page);
}

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

function styleFromRect(rect, page) {
  const [px0, py0, pw, ph] = page;
  return {
    left: `${((rect[0] - px0) / pw) * 100}%`,
    top: `${((rect[1] - py0) / ph) * 100}%`,
    width: `${Math.max(8, ((rect[2] - rect[0]) / pw) * 100)}%`,
    height: `${Math.max(8, ((rect[3] - rect[1]) / ph) * 100)}%`,
  };
}

/**
 * 서명 편집 오버레이 (원본 SignatureStampOverlay).
 * 미리보기 크기가 곧 PDF 확정 크기(WYSIWYG). Enter/더블클릭=확정, Esc=취소, Delete=삭제.
 */
export default function SignatureStampOverlay({
  png,
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

  /** 안쪽은 이동, 가장자리/바깥 핸들만 크기 조절. 작은 서명에서 핸들에 전부 먹히지 않게. */
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
    let best = null;
    let bestDist = HANDLE_HIT;
    for (const name of HANDLES) {
      const [hx, hy] = points[name];
      const dist = Math.hypot(localX - hx, localY - hy);
      if (dist <= bestDist) {
        best = name;
        bestDist = dist;
      }
    }
    if (best) return best;
    // 아주 작은 상자: 가장자리 12% 안쪽도 가까운 변/모서리로 본다.
    const edge = Math.max(6, Math.min(widthPx, heightPx) * 0.12);
    const nearL = localX <= edge;
    const nearR = localX >= widthPx - edge;
    const nearT = localY <= edge;
    const nearB = localY >= heightPx - edge;
    if (nearT && nearL) return 'nw';
    if (nearT && nearR) return 'ne';
    if (nearB && nearL) return 'sw';
    if (nearB && nearR) return 'se';
    if (nearT) return 'n';
    if (nearB) return 's';
    if (nearL) return 'w';
    if (nearR) return 'e';
    return null;
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

  function onPointerDown(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const el = rootRef.current;
    const localX = event.clientX - el.getBoundingClientRect().left;
    const localY = event.clientY - el.getBoundingClientRect().top;
    const handle = hitHandle(localX, localY, el.clientWidth, el.clientHeight) || 'move';
    const point = pagePointFromClient(event.clientX, event.clientY);
    dragRef.current = { handle, origin: [...liveRectRef.current], point };
    onDraggingChange?.(true);
    el.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event) {
    const drag = dragRef.current;
    if (!drag) {
      const el = rootRef.current;
      if (!el) return;
      const localX = event.clientX - el.getBoundingClientRect().left;
      const localY = event.clientY - el.getBoundingClientRect().top;
      const handle = hitHandle(localX, localY, el.clientWidth, el.clientHeight);
      el.style.cursor = handle ? HANDLE_CURSOR[handle] : 'move';
      return;
    }
    const point = pagePointFromClient(event.clientX, event.clientY);
    if (drag.handle === 'move') {
      applyLive(moveRect(drag.origin, point.x - drag.point.x, point.y - drag.point.y, page));
    } else {
      applyLive(resizeRect(drag.origin, drag.handle, point, imageWidth, imageHeight, page));
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
      aria-label="서명 편집"
      data-sig-overlay="1"
      className="absolute z-20 outline-none"
      style={{
        ...box,
        cursor: 'move',
        outline: '1px dashed #2563eb',
        outlineOffset: 0,
        boxSizing: 'border-box',
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
        src={`data:image/png;base64,${png}`}
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
