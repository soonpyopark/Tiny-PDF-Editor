import { useEffect, useRef } from 'react';
import { HANDLES, clampRectToPage, handlePoint, resizeRect, styleFromRect } from './imageBoxMath.js';
import { normalizeCrop, visibleAspect } from './imageEditMath.js';

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
 * 고른 이미지 하나의 편집 오버레이. 화면에 보이는 상자 = item.rect = PDF 에 확정되는 rect (WYSIWYG).
 * 드래그=이동(여러 개를 골랐으면 같이), 핸들=크기(비율 유지, Alt=가운데 기준), Ctrl=이동 중 자석 끄기,
 * 더블클릭=확정. 잠긴 이미지는 고르기만 되고 움직이지 않는다.
 * 자르기·투명도는 CSS 로 미리 보여 주고(미리보기 그림은 자르기 전 그림), 확정할 때 엔진이 실제로 적용한다.
 */
export default function ImagePlaceOverlay({ item, eyedrop, onBegin, onMove, onResize, onEnd, onCommit, onPickColor }) {
  const rootRef = useRef(null);
  const dragRef = useRef(null);
  const rectRef = useRef(item.rect);
  rectRef.current = item.rect;
  const [px0, py0, pw, ph] = item.page;
  const locked = Boolean(item.params.lock);

  useEffect(() => {
    rootRef.current?.focus({ preventScroll: true });
  }, []);

  function pagePointFromClient(clientX, clientY) {
    const host = rootRef.current?.offsetParent;
    if (!host) return { x: rectRef.current[0], y: rectRef.current[1] };
    const box = host.getBoundingClientRect();
    return {
      x: px0 + ((clientX - box.left) / Math.max(1, box.width)) * pw,
      y: py0 + ((clientY - box.top) / Math.max(1, box.height)) * ph,
    };
  }

  function localPoint(event) {
    const box = rootRef.current.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top, w: box.width, h: box.height };
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

  function endDrag(event) {
    if (!dragRef.current) return;
    dragRef.current = null;
    onEnd();
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
    rootRef.current?.focus({ preventScroll: true });
    const local = localPoint(event);
    if (eyedrop) {
      onPickColor(item.key, local.x / Math.max(1, local.w), local.y / Math.max(1, local.h));
      return;
    }
    if (locked) return;
    const handle = hitHandle(local.x, local.y, local.w, local.h) || 'move';
    const point = pagePointFromClient(event.clientX, event.clientY);
    const origin = [...rectRef.current];
    // 핸들을 잡은 자리와 핸들 중심의 차이. 이걸 빼 줘야 잡는 순간 상자가 튀지 않고 핸들이 커서에 붙어 따라온다.
    const anchor = handle === 'move' ? null : handlePoint(origin, handle);
    const grab = anchor ? { x: point.x - anchor[0], y: point.y - anchor[1] } : null;
    dragRef.current = { handle, origin, point, grab };
    onBegin(item.key);
    rootRef.current.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event) {
    const drag = dragRef.current;
    const el = rootRef.current;
    if (!drag) {
      if (!el) return;
      if (eyedrop) {
        el.style.cursor = 'crosshair';
        return;
      }
      if (locked) {
        el.style.cursor = 'default';
        return;
      }
      const local = localPoint(event);
      const handle = hitHandle(local.x, local.y, local.w, local.h);
      el.style.cursor = handle ? HANDLE_CURSOR[handle] : 'move';
      return;
    }
    const point = pagePointFromClient(event.clientX, event.clientY);
    if (drag.handle === 'move') {
      onMove(point.x - drag.point.x, point.y - drag.point.y, event.ctrlKey || event.metaKey);
      return;
    }
    const aspect = visibleAspect(item.params);
    if (event.altKey) {
      // 가운데 기준: 반대쪽 모서리 대신 가운데를 고정한다.
      const [x0, y0, x1, y1] = drag.origin;
      const cx = (x0 + x1) / 2;
      const cy = (y0 + y1) / 2;
      const fixed = handlePoint(drag.origin, { nw: 'se', n: 's', ne: 'sw', e: 'w', se: 'nw', s: 'n', sw: 'ne', w: 'e' }[drag.handle]);
      const target = { x: point.x - (drag.grab?.x ?? 0), y: point.y - (drag.grab?.y ?? 0) };
      const mirrored = { x: fixed[0] + 2 * (target.x - cx), y: fixed[1] + 2 * (target.y - cy) };
      const grown = resizeRect(drag.origin, drag.handle, mirrored, aspect, item.page, null);
      const w = grown[2] - grown[0];
      const h = grown[3] - grown[1];
      onResize(item.key, clampRectToPage([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], item.page));
      return;
    }
    onResize(item.key, resizeRect(drag.origin, drag.handle, point, aspect, item.page, drag.grab));
  }

  const [cl, ct, cr, cb] = normalizeCrop(item.params.crop);
  const visW = Math.max(0.05, 1 - cl - cr);
  const visH = Math.max(0.05, 1 - ct - cb);
  const box = styleFromRect(item.rect, item.page);

  return (
    <div
      ref={rootRef}
      tabIndex={0}
      role="button"
      aria-label="이미지 편집"
      data-img-overlay="1"
      data-img-key={item.key}
      data-img-locked={locked ? '1' : '0'}
      className="absolute z-20 outline-none"
      style={{
        ...box,
        cursor: locked ? 'default' : 'move',
        outline: locked ? '1px solid #94a3b8' : '1px dashed #2563eb',
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
      onContextMenu={(event) => event.preventDefault()}
    >
      <div className="pointer-events-none absolute inset-0 overflow-hidden" style={{ opacity: item.params.op / 100 }}>
        <img
          src={`data:image/png;base64,${item.preview}`}
          alt=""
          draggable={false}
          className="pointer-events-none absolute select-none"
          style={{
            width: `${100 / visW}%`,
            height: `${100 / visH}%`,
            left: `${(-cl / visW) * 100}%`,
            top: `${(-ct / visH) * 100}%`,
            maxWidth: 'none',
          }}
        />
      </div>
      {locked ? (
        <span
          aria-label="잠김"
          className="pointer-events-none absolute right-0.5 top-0.5 rounded bg-slate-700/80 px-1 text-[10px] leading-4 text-white"
        >
          잠김
        </span>
      ) : (
        HANDLES.map((name) => <span key={name} aria-hidden style={handleBox(name)} />)
      )}
    </div>
  );
}
