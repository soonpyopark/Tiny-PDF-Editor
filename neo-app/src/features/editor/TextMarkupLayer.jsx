import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../../lib/apiClient.js';
import { useMenuPlacement } from '../../lib/menuPlacement.js';

// 원본 pdf_editor/highlight_colors.py 프리셋. 형광펜은 연한 색, 밑줄은 진한 색.
const HIGHLIGHT_COLORS = [
  { id: 'gray', label: '회색', hex: '#e0e0e0' },
  { id: 'yellow', label: '노랑', hex: '#fff59d' },
  { id: 'red', label: '분홍', hex: '#ffcdd2' },
  { id: 'blue', label: '파랑', hex: '#bbdefb' },
  { id: 'green', label: '초록', hex: '#c8e6c9' },
];
const UNDERLINE_COLORS = [
  { id: 'gray', label: '회색', hex: '#616161' },
  { id: 'yellow', label: '노랑', hex: '#f9a825' },
  { id: 'red', label: '빨강', hex: '#e53935' },
  { id: 'blue', label: '파랑', hex: '#1e88e5' },
  { id: 'green', label: '초록', hex: '#43a047' },
];
// 원본 DEFAULT_HIGHLIGHT_COLOR_ID / DEFAULT_UNDERLINE_COLOR_ID 와 같은 기본값. 마지막으로 고른 색을 기억한다.
const preferredColor = { highlight: 'yellow', underline: 'red' };
const PREVIEW_INTERVAL_MS = 90;
const MIN_DRAG = 0.004;

function paletteOf(kind) {
  return kind === 'underline' ? UNDERLINE_COLORS : HIGHLIGHT_COLORS;
}

function hexToRgb01(hex) {
  const value = parseInt(hex.slice(1), 16);
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255];
}

function clamp01(value) {
  return Math.min(1, Math.max(0, value));
}

function rectStyle(rect) {
  return {
    left: `${rect[0] * 100}%`,
    top: `${rect[1] * 100}%`,
    width: `${(rect[2] - rect[0]) * 100}%`,
    height: `${(rect[3] - rect[1]) * 100}%`,
  };
}

/** 요소를 감싸는 스크롤/클립 영역의 보이는 범위(뷰포트 좌표). 없으면 창 전체. */
function visibleBoxOf(element) {
  let node = element.parentElement;
  while (node && node !== document.body) {
    if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(node).overflowY)) {
      const r = node.getBoundingClientRect();
      return {
        left: Math.max(0, r.left),
        top: Math.max(0, r.top),
        right: Math.min(window.innerWidth, r.right),
        bottom: Math.min(window.innerHeight, r.bottom),
      };
    }
    node = node.parentElement;
  }
  return { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
}

function ColorGroup({ label, kind, disabled, onPick }) {
  return (
    <div className="flex shrink-0 items-center gap-1">
      <span className="w-12 shrink-0 whitespace-nowrap px-1 text-[12px] font-medium text-slate-600">{label}</span>
      {paletteOf(kind).map((color) => (
        <button
          key={color.id}
          type="button"
          disabled={disabled}
          title={`${label} - ${color.label}`}
          aria-label={`${label} ${color.label}`}
          onClick={() => onPick(kind, color.id)}
          className="h-3 w-3 rounded-full border border-slate-300 hover:scale-110 disabled:opacity-40"
          style={{ backgroundColor: color.hex }}
        />
      ))}
    </div>
  );
}

/**
 * 쪽 이미지 위에 겹치는 드래그 선택 레이어 (원본 PageCanvas 의 텍스트 선택 + 형광펜·밑줄).
 * 좌표는 쪽 이미지 기준 0..1 비율로 주고받으므로 확대/축소와 무관하다.
 * 형광펜·밑줄은 엔진이 PDF 에 주석으로 넣고, 쪽 이미지를 다시 그려서 보인다.
 */
export default function TextMarkupLayer({ pageIndex, enabled, onMarkupChanged, onNotice, onEmptyClick }) {
  const layerRef = useRef(null);
  const dragRef = useRef(null);
  const previewAtRef = useRef(0);
  const seqRef = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState(null);
  const [sel, setSel] = useState(null); // { anchor, cursor, text, rects }
  const [menu, setMenu] = useState(null); // { x, y, point }
  const [busy, setBusy] = useState(false);
  const menuRef = useMenuPlacement(Boolean(menu), menu?.x ?? 0, menu?.y ?? 0);
  const toolbarRef = useRef(null);
  const [toolbarPos, setToolbarPos] = useState(null); // 레이어 기준 px 좌표

  // 쪽이 바뀌면 선택과 메뉴를 버리고, 진행 중인 선택 응답은 무시한다.
  useEffect(() => {
    seqRef.current += 1;
    dragRef.current = null;
    setDragging(false);
    setPreview(null);
    setSel(null);
    setMenu(null);
  }, [pageIndex]);

  useEffect(() => {
    if (!menu) return undefined;
    const onDown = (event) => {
      if (menuRef.current?.contains(event.target)) return;
      setMenu(null);
    };
    const onKey = (event) => {
      if (event.key === 'Escape') setMenu(null);
    };
    window.addEventListener('pointerdown', onDown, true);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  useEffect(() => {
    if (!sel) return undefined;
    const onKey = (event) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'c') {
        event.preventDefault();
        void navigator.clipboard?.writeText(sel.text).catch(() => onNotice('복사하지 못했습니다.'));
      } else if (event.key === 'Escape') {
        setSel(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sel, onNotice]);

  function pointFromEvent(event) {
    const box = layerRef.current.getBoundingClientRect();
    return {
      x: clamp01((event.clientX - box.left) / box.width),
      y: clamp01((event.clientY - box.top) / box.height),
    };
  }

  // 응답이 도착했을 때 더 최신 요청이 있으면 null 을 돌려 버린다.
  async function queryRange(anchor, cursor) {
    const seq = ++seqRef.current;
    const result = await api('pdf.textSelect', { index: pageIndex, anchor, cursor });
    return seq === seqRef.current ? result : null;
  }

  function onPointerDown(event) {
    if (event.button !== 0) return;
    setMenu(null);
    if (!enabled || busy) return;
    const point = pointFromEvent(event);
    layerRef.current.setPointerCapture(event.pointerId);
    dragRef.current = { anchor: point, cursor: point };
    previewAtRef.current = 0;
    setSel(null);
    setPreview(null);
    setDragging(true);
  }

  function onPointerMove(event) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(event);
    drag.cursor = point;
    const now = performance.now();
    if (now - previewAtRef.current < PREVIEW_INTERVAL_MS) return;
    previewAtRef.current = now;
    void queryRange(drag.anchor, point)
      .then((result) => {
        if (result && dragRef.current) setPreview(result.text.trim() ? result : null);
      })
      .catch(() => {});
  }

  async function onPointerUp(event) {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    setDragging(false);
    setPreview(null);
    const point = pointFromEvent(event);
    if (Math.abs(point.x - drag.anchor.x) < MIN_DRAG && Math.abs(point.y - drag.anchor.y) < MIN_DRAG) {
      setSel(null);
      onEmptyClick?.(point);
      return;
    }
    try {
      const result = await queryRange(drag.anchor, point);
      if (result && result.text.trim()) {
        setSel({ anchor: drag.anchor, cursor: point, text: result.text, rects: result.rects });
      } else {
        setSel(null);
      }
    } catch (err) {
      setSel(null);
      onNotice(err instanceof Error ? err.message : '텍스트를 선택하지 못했습니다.');
    }
  }

  function copySelection() {
    if (!sel) return;
    void navigator.clipboard?.writeText(sel.text).catch(() => onNotice('복사하지 못했습니다.'));
  }

  // 우클릭 메뉴에서 색을 고르면 메뉴를 닫고 바로 표시한다.
  function pickFromMenu(kind, colorId) {
    setMenu(null);
    void apply(kind, colorId);
  }

  async function apply(kind, colorId) {
    if (!sel || busy) return;
    const color = paletteOf(kind).find((item) => item.id === colorId) ?? paletteOf(kind)[0];
    preferredColor[kind] = color.id;
    setBusy(true);
    try {
      const result = await api('pdf.markupAdd', {
        index: pageIndex,
        kind,
        anchor: sel.anchor,
        cursor: sel.cursor,
        color: hexToRgb01(color.hex),
      });
      setSel(null);
      if (result.applied) {
        onMarkupChanged(result.doc);
      } else {
        onNotice('선택한 영역에서 표시할 글자를 찾지 못했습니다.');
      }
    } catch (err) {
      onNotice(err instanceof Error ? err.message : '표시하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  async function removeAtMenuPoint() {
    if (!menu || busy) return;
    const point = menu.point;
    setMenu(null);
    setBusy(true);
    try {
      const result = await api('pdf.markupRemove', { index: pageIndex, point });
      if (result.removed) {
        onMarkupChanged(result.doc);
      } else {
        onNotice('이 위치에는 형광펜이나 밑줄이 없습니다.');
      }
    } catch (err) {
      onNotice(err instanceof Error ? err.message : '지우지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  const view = dragging ? preview : sel;
  const lastRect = view?.rects?.[view.rects.length - 1];
  const menuHasSelection = Boolean(sel);

  // 선택 도구 모음은 드래그를 놓은 마지막 포인터 위치 부근(오른쪽 아래)에 연다.
  // 공간이 모자라면 왼쪽/위로 뒤집고, 보이는 영역 안으로 맞춘다. 원본 우클릭 메뉴 배치와 같은 규칙.
  useLayoutEffect(() => {
    if (dragging || !sel || !toolbarRef.current || !layerRef.current) {
      setToolbarPos(null);
      return;
    }
    const layer = layerRef.current.getBoundingClientRect();
    const box = visibleBoxOf(layerRef.current);
    const w = toolbarRef.current.offsetWidth;
    const h = toolbarRef.current.offsetHeight;
    const pointerX = layer.left + sel.cursor.x * layer.width;
    const pointerY = layer.top + sel.cursor.y * layer.height;
    const margin = 6;

    let x = pointerX + margin;
    if (x + w > box.right - margin) x = pointerX - margin - w;
    x = Math.max(box.left + margin, Math.min(x, box.right - w - margin));

    let y = pointerY + margin;
    if (y + h > box.bottom - margin) y = pointerY - margin - h;
    y = Math.max(box.top + margin, Math.min(y, box.bottom - h - margin));

    setToolbarPos({ left: x - layer.left, top: y - layer.top });
  }, [sel, dragging]);

  return (
    <>
      <div
        ref={layerRef}
        className={`absolute inset-0 select-none ${enabled ? 'cursor-text' : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(event) => void onPointerUp(event)}
        onPointerCancel={() => {
          dragRef.current = null;
          setDragging(false);
          setPreview(null);
        }}
        onContextMenu={(event) => {
          if (!enabled) return;
          event.preventDefault();
          setMenu({ x: event.clientX, y: event.clientY, point: pointFromEvent(event) });
        }}
      >
        {view?.rects?.map((rect, index) => (
          <div
            key={index}
            className="pointer-events-none absolute bg-app-accent/25"
            style={rectStyle(rect)}
          />
        ))}
      </div>

      {!dragging && sel && lastRect ? (
        <div
          ref={toolbarRef}
          role="toolbar"
          aria-label="선택 영역 도구"
          className="absolute z-20 flex w-max max-w-none flex-col items-stretch gap-1 whitespace-nowrap rounded-lg border border-app-border bg-white px-1.5 py-1 text-[12px] text-slate-700 shadow-lg"
          style={{
            left: toolbarPos?.left ?? 0,
            top: toolbarPos?.top ?? 0,
            visibility: toolbarPos ? 'visible' : 'hidden',
          }}
        >
          {/* 1행: 형광펜 색, 2행: 밑줄 색, 3행: 복사 · 선택 해제 */}
          <ColorGroup label="형광펜" kind="highlight" disabled={busy} onPick={apply} />
          <span className="h-px w-full bg-slate-200" />
          <ColorGroup label="밑줄" kind="underline" disabled={busy} onPick={apply} />
          <span className="h-px w-full bg-slate-200" />
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={copySelection}
              className="h-6 shrink-0 whitespace-nowrap rounded px-2 hover:bg-app-accentSoft"
              title="선택한 글자 복사 (Ctrl+C)"
            >
              복사
            </button>
            <button
              type="button"
              onClick={() => setSel(null)}
              className="ml-auto h-6 w-6 rounded text-slate-500 hover:bg-slate-100"
              aria-label="선택 해제"
              title="선택 해제 (Esc)"
            >
              ×
            </button>
          </div>
        </div>
      ) : null}

      {menu ? (
        <div
          ref={menuRef}
          role="menu"
          className="fixed z-[3000] flex w-max min-w-[210px] flex-col items-stretch gap-1 whitespace-nowrap rounded-lg border border-app-border bg-white px-1.5 py-1 text-[12px] text-slate-700 shadow-lg"
          onContextMenu={(event) => event.preventDefault()}
        >
          {/* 드래그로 나오는 도구 모음과 같은 구성: 1행 형광펜 색, 2행 밑줄 색, 3행 복사 · 선택 해제 */}
          <ColorGroup label="형광펜" kind="highlight" disabled={busy || !menuHasSelection} onPick={pickFromMenu} />
          <span className="h-px w-full bg-slate-200" />
          <ColorGroup label="밑줄" kind="underline" disabled={busy || !menuHasSelection} onPick={pickFromMenu} />
          <span className="h-px w-full bg-slate-200" />
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={!menuHasSelection}
              onClick={() => {
                setMenu(null);
                copySelection();
              }}
              className="h-6 shrink-0 whitespace-nowrap rounded px-2 hover:bg-app-accentSoft disabled:text-slate-400 disabled:hover:bg-transparent"
              title="선택한 글자 복사 (Ctrl+C)"
            >
              복사
            </button>
            <button
              type="button"
              onClick={() => {
                setMenu(null);
                setSel(null);
              }}
              className="ml-auto h-6 w-6 rounded text-slate-500 hover:bg-slate-100"
              aria-label="선택 해제"
              title="선택 해제 (Esc)"
            >
              ×
            </button>
          </div>
          {/* 이 아래는 기존 기능 그대로: 이 위치의 형광펜·밑줄 지우기 */}
          <span className="h-px w-full bg-slate-200" />
          <button
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={() => void removeAtMenuPoint()}
            className="h-6 whitespace-nowrap rounded px-2 text-left hover:bg-app-accentSoft disabled:text-slate-400 disabled:hover:bg-transparent"
          >
            이 위치의 형광펜·밑줄 지우기
          </button>
        </div>
      ) : null}
    </>
  );
}

