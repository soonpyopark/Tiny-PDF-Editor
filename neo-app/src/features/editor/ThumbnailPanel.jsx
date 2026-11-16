import { useEffect, useMemo, useRef, useState } from 'react';
import { useMenuPlacement } from '../../lib/menuPlacement.js';

/** Matches pdf_editor.thumbnail_panel.THUMB_SCALE_LEVELS */
export const THUMB_SCALE_LEVELS = [55, 95, 135, 165];
export const DEFAULT_THUMB_SCALE_LEVEL = 2;

const headerBtnClass =
  'inline-flex h-[26px] w-7 shrink-0 items-center justify-center rounded text-[#333] hover:bg-slate-100 disabled:opacity-40';

function selectionHeaderText(indices) {
  if (!indices.length) return '선택된 페이지 없음';
  const pages = indices.map((index) => index + 1);
  if (pages.length === 1) return `선택한 페이지 1개 (${pages[0]}페이지)`;
  const consecutive = pages.every((page, i) => i === 0 || page === pages[i - 1] + 1);
  if (consecutive) return `선택한 페이지 ${pages.length}개 (${pages[0]}–${pages.at(-1)})`;
  return `선택한 페이지 ${pages.length}개`;
}

function selectionActionLabel(verb, indices, particle = '') {
  if (!indices.length) return verb;
  const target = indices.length === 1 ? `${indices[0] + 1}페이지` : `선택한 ${indices.length}개 페이지`;
  return particle ? `${target}${particle}${verb}` : `${target} ${verb}`;
}

function scopedLabel(verb, indices) {
  if (!indices.length) return verb;
  if (indices.length === 1) return `${indices[0] + 1}페이지 ${verb}`;
  return `선택한 ${indices.length}개 페이지 ${verb}`;
}

function ocrLabel(indices) {
  if (!indices.length) return 'OCR 실행';
  if (indices.length === 1) return `${indices[0] + 1}페이지 OCR 실행`;
  return `선택된 ${indices.length}개 페이지 OCR 실행`;
}

/**
 * Tiny ThumbnailPanel port: multi-select, header actions, context menu, reorder drag, file drop.
 *
 * @param {{
 *   docOpen: boolean,
 *   thumbs: string[],
 *   pageIndex: number,
 *   pageCount: number,
 *   clipboardCount?: number,
 *   onSelectPage: (index: number) => void,
 *   onAction: (action: { type: string, indices?: number[], targetIndex?: number, degrees?: number, paths?: string[] }) => void,
 * }} props
 */
export default function ThumbnailPanel({
  docOpen,
  thumbs,
  pageIndex,
  pageCount,
  clipboardCount = 0,
  onSelectPage,
  onAction,
}) {
  const [selected, setSelected] = useState(/** @type {number[]} */ ([]));
  const [scaleLevel, setScaleLevel] = useState(DEFAULT_THUMB_SCALE_LEVEL);
  const [menu, setMenu] = useState(/** @type {null | { x: number, y: number, insertIndex: number, indices: number[] }} */ (null));
  const [dragOverIndex, setDragOverIndex] = useState(/** @type {number | null} */ (null));
  const anchorRef = useRef(0);
  const listRef = useRef(null);
  const menuRef = useMenuPlacement(Boolean(menu), menu?.x ?? 0, menu?.y ?? 0);
  const itemRefs = useRef(/** @type {(HTMLButtonElement | null)[]} */ ([]));
  // 빈 영역 드래그(사각형 선택) 상태. 원본 ThumbnailListWidget 의 rubber band 와 같다.
  const bandDragRef = useRef(/** @type {null | { origin: {x: number, y: number}, base: number[], additive: boolean, moved: boolean, lastCurrent: number }} */ (null));
  const [bandRect, setBandRect] = useState(/** @type {null | { left: number, top: number, width: number, height: number }} */ (null));

  const thumbWidth = THUMB_SCALE_LEVELS[Math.max(0, Math.min(THUMB_SCALE_LEVELS.length, scaleLevel) - 1)];

  useEffect(() => {
    if (!docOpen || pageCount <= 0) {
      setSelected([]);
      return;
    }
    setSelected((prev) => {
      const next = prev.filter((index) => index >= 0 && index < pageCount);
      if (next.length) return next;
      return [Math.max(0, Math.min(pageIndex, pageCount - 1))];
    });
  }, [docOpen, pageCount, pageIndex]);

  // 원본 ThumbnailListWidget.scroll_to_row(EnsureVisible)와 같다:
  // 뷰어에서 쪽이 바뀌면(이전/다음, 쪽 번호 입력, 검색 등) 현재 썸네일이 보이도록만 스크롤한다.
  // 이미 보이면 목록을 움직이지 않는다.
  useEffect(() => {
    if (!docOpen) return;
    const list = listRef.current;
    const item = itemRefs.current[pageIndex];
    if (!list || !item) return;
    const listRect = list.getBoundingClientRect();
    const itemRect = item.getBoundingClientRect();
    if (itemRect.top < listRect.top) {
      list.scrollTop -= listRect.top - itemRect.top;
    } else if (itemRect.bottom > listRect.bottom) {
      list.scrollTop += itemRect.bottom - listRect.bottom;
    }
  }, [docOpen, pageIndex, thumbs.length]);

  useEffect(() => {
    if (!menu) return undefined;
    const close = () => setMenu(null);
    window.addEventListener('click', close);
    window.addEventListener('blur', close);
    window.addEventListener('resize', close);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('blur', close);
      window.removeEventListener('resize', close);
    };
  }, [menu]);

  // 원본 ThumbnailListWidget.wheelEvent: Ctrl+휠로 썸네일 크기 단계를 바꾼다.
  // 브라우저 기본 확대/축소를 막아야 하므로 네이티브 리스너(passive: false)를 직접 건다.
  useEffect(() => {
    const list = listRef.current;
    if (!list) return undefined;
    function onCtrlWheel(event) {
      if (!event.ctrlKey || !event.deltaY) return;
      event.preventDefault();
      changeScale(event.deltaY < 0 ? 1 : -1);
    }
    list.addEventListener('wheel', onCtrlWheel, { passive: false });
    return () => list.removeEventListener('wheel', onCtrlWheel);
  }, []);

  const sortedSelected = useMemo(() => [...selected].sort((a, b) => a - b), [selected]);

  function selectOnly(index) {
    setSelected([index]);
    anchorRef.current = index;
    onSelectPage(index);
  }

  function toggleSelect(index) {
    setSelected((prev) => {
      const has = prev.includes(index);
      const next = has ? prev.filter((value) => value !== index) : [...prev, index].sort((a, b) => a - b);
      return next.length ? next : [index];
    });
    anchorRef.current = index;
    onSelectPage(index);
  }

  function rangeSelect(index) {
    const from = anchorRef.current;
    const start = Math.min(from, index);
    const end = Math.max(from, index);
    const next = [];
    for (let i = start; i <= end; i += 1) next.push(i);
    setSelected(next);
    onSelectPage(index);
  }

  function onItemClick(event, index) {
    if (event.shiftKey) rangeSelect(index);
    else if (event.ctrlKey || event.metaKey) toggleSelect(index);
    else selectOnly(index);
  }

  function openMenu(event, index) {
    event.preventDefault();
    event.stopPropagation();
    const indices = selected.includes(index) ? sortedSelected : [index];
    if (!selected.includes(index)) {
      setSelected([index]);
      onSelectPage(index);
    }
    setMenu({
      x: event.clientX,
      y: event.clientY,
      insertIndex: index,
      indices,
    });
  }

  function openEmptyMenu(event) {
    event.preventDefault();
    setMenu({
      x: event.clientX,
      y: event.clientY,
      insertIndex: pageCount,
      indices: sortedSelected,
    });
  }

  function run(type, extra = {}) {
    setMenu(null);
    onAction({ type, indices: sortedSelected, ...extra });
  }

  function changeScale(step) {
    setScaleLevel((prev) => Math.max(1, Math.min(THUMB_SCALE_LEVELS.length, prev + step)));
  }

  // 원본 ThumbnailListWidget.keyPressEvent: Ctrl+Z/Ctrl+Y(재실행), Ctrl+A, Esc, Delete/Backspace.
  function onPanelKeyDown(event) {
    const ctrl = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (ctrl && key === 'z' && !event.shiftKey) {
      if (!docOpen) return;
      event.preventDefault();
      onAction({ type: 'undo' });
      return;
    }
    if (ctrl && (key === 'y' || (key === 'z' && event.shiftKey))) {
      if (!docOpen) return;
      event.preventDefault();
      onAction({ type: 'redo' });
      return;
    }
    if (ctrl && key === 'a') {
      if (!docOpen || pageCount <= 0) return;
      event.preventDefault();
      setSelected(Array.from({ length: pageCount }, (_, i) => i));
      return;
    }
    if (event.key === 'Escape') {
      setSelected([]);
      return;
    }
    if (event.key === 'Delete' || event.key === 'Backspace') {
      if (!docOpen || !sortedSelected.length) return;
      event.preventDefault();
      run('delete');
    }
  }

  function listContentPoint(clientX, clientY) {
    const list = listRef.current;
    const rect = list.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top + list.scrollTop };
  }

  // 썸네일 버튼이 아닌 빈 영역(카드 사이 여백 포함)에서 누르면 사각형 선택을 시작한다.
  function onListMouseDown(event) {
    if (event.button !== 0 || !docOpen || pageCount <= 0) return;
    if (event.target instanceof Element && event.target.closest('button')) return;
    const additive = event.ctrlKey || event.metaKey;
    const origin = listContentPoint(event.clientX, event.clientY);
    bandDragRef.current = {
      origin,
      base: additive ? sortedSelected : [],
      additive,
      moved: false,
      lastCurrent: pageIndex,
    };
    if (!additive) setSelected([]);
    window.addEventListener('mousemove', onBandMove);
    window.addEventListener('mouseup', onBandUp);
  }

  function onBandMove(event) {
    const drag = bandDragRef.current;
    const list = listRef.current;
    if (!drag || !list) return;
    const cur = listContentPoint(event.clientX, event.clientY);
    if (!drag.moved && Math.hypot(cur.x - drag.origin.x, cur.y - drag.origin.y) < 4) return;
    drag.moved = true;
    const left = Math.min(drag.origin.x, cur.x);
    const right = Math.max(drag.origin.x, cur.x);
    const top = Math.min(drag.origin.y, cur.y);
    const bottom = Math.max(drag.origin.y, cur.y);
    setBandRect({ left, top, width: right - left, height: bottom - top });

    const listRect = list.getBoundingClientRect();
    const hits = [];
    for (let i = 0; i < pageCount; i += 1) {
      const element = itemRefs.current[i];
      if (!element) continue;
      const r = element.getBoundingClientRect();
      const t = r.top - listRect.top + list.scrollTop;
      const b = t + r.height;
      const l = r.left - listRect.left;
      const rt = l + r.width;
      if (rt >= left && l <= right && b >= top && t <= bottom) hits.push(i);
    }
    const next = drag.additive ? [...new Set([...drag.base, ...hits])].sort((a, b) => a - b) : hits;
    setSelected(next);
    if (hits.length) {
      const current = Math.max(...hits);
      if (current !== drag.lastCurrent) {
        drag.lastCurrent = current;
        onSelectPage(current);
      }
    }
  }

  function onBandUp() {
    const drag = bandDragRef.current;
    bandDragRef.current = null;
    window.removeEventListener('mousemove', onBandMove);
    window.removeEventListener('mouseup', onBandUp);
    setBandRect(null);
    // 제자리 클릭(이동 없음)이면 현재 쪽만 남긴다. 원본 clear_selection_except_current 와 같다.
    if (drag && !drag.moved && !drag.additive) setSelected([pageIndex]);
  }

  function onDragStart(event, index) {
    const indices = selected.includes(index) ? sortedSelected : [index];
    if (!selected.includes(index)) {
      setSelected([index]);
      onSelectPage(index);
    }
    event.dataTransfer.setData('application/x-tiny-pages', JSON.stringify(indices));
    event.dataTransfer.effectAllowed = 'move';
  }

  function onDragOverItem(event, index) {
    event.preventDefault();
    setDragOverIndex(index);
    event.dataTransfer.dropEffect = event.dataTransfer.types.includes('Files') ? 'copy' : 'move';
  }

  function onDropAt(event, targetIndex) {
    event.preventDefault();
    setDragOverIndex(null);
    // Sandboxed renderer cannot read File.path; open Tiny's insert dialog instead.
    if (event.dataTransfer.files?.length) {
      onAction({ type: 'insertFiles', targetIndex });
      return;
    }
    try {
      const raw = event.dataTransfer.getData('application/x-tiny-pages');
      const indices = JSON.parse(raw || '[]');
      if (Array.isArray(indices) && indices.length) {
        onAction({ type: 'movePages', indices: indices.map(Number), targetIndex });
      }
    } catch {
      /* ignore */
    }
  }

  const menuIndices = menu?.indices ?? [];
  const insertAt = (menu?.insertIndex ?? 0) + 1;

  return (
    <aside
      className="flex w-64 shrink-0 flex-col border-r border-[#cccccc] bg-white"
      onKeyDown={onPanelKeyDown}
    >
      <div className="flex h-[34px] items-center gap-0.5 border-b border-[#cccccc] px-1">
        <span className="min-w-0 flex-1 truncate px-1 text-xs font-medium text-[#333]">썸네일</span>
        <button type="button" className={headerBtnClass} title="썸네일 축소" disabled={scaleLevel <= 1} onClick={() => changeScale(-1)}>
          −
        </button>
        <button
          type="button"
          className={headerBtnClass}
          title="썸네일 확대"
          disabled={scaleLevel >= THUMB_SCALE_LEVELS.length}
          onClick={() => changeScale(1)}
        >
          +
        </button>
      </div>

      <div
        ref={listRef}
        className="relative min-h-0 flex-1 overflow-auto p-2"
        title="페이지를 드래그해 순서를 바꾸거나, 파일을 끌어다 놓으세요"
        onMouseDown={onListMouseDown}
        onContextMenu={openEmptyMenu}
        onDragOver={(event) => {
          event.preventDefault();
          setDragOverIndex(pageCount);
        }}
        onDrop={(event) => onDropAt(event, pageCount)}
        onDragLeave={() => setDragOverIndex(null)}
      >
        {!docOpen ? (
          <p className="px-1 text-xs leading-relaxed text-slate-400">연 문서의 쪽 미리보기가 여기 표시됩니다.</p>
        ) : (
          thumbs.map((src, index) => {
            const isSelected = selected.includes(index);
            const isCurrent = index === pageIndex;
            const showLine = dragOverIndex === index;
            return (
              <div key={index} className="relative">
                {showLine ? <DropLine /> : null}
                <button
                  ref={(element) => {
                    itemRefs.current[index] = element;
                  }}
                  type="button"
                  draggable
                  onClick={(event) => onItemClick(event, index)}
                  onContextMenu={(event) => openMenu(event, index)}
                  onDragStart={(event) => onDragStart(event, index)}
                  onDragOver={(event) => onDragOverItem(event, index)}
                  onDrop={(event) => onDropAt(event, index)}
                  className={`mb-2 block w-full rounded-md border p-1 text-left ${
                    isSelected
                      ? 'border-[#d93025] bg-[#ebebeb]'
                      : isCurrent
                        ? 'border-[#f28b82] bg-white'
                        : 'border-[#666666] bg-white hover:bg-slate-50'
                  }`}
                >
                  <div
                    className="mx-auto flex items-center justify-center overflow-hidden bg-slate-100"
                    style={{ width: thumbWidth, height: Math.max(45, Math.round(thumbWidth * 1.4)) }}
                  >
                    {src ? (
                      <img src={src} alt="" className="max-h-full max-w-full" draggable={false} />
                    ) : (
                      <span className="text-xs text-slate-400">{index + 1}</span>
                    )}
                  </div>
                  <div className="pt-1 text-center text-xs text-slate-500">{index + 1}</div>
                </button>
              </div>
            );
          })
        )}
        {dragOverIndex === pageCount && docOpen ? <DropLine className="relative" /> : null}
        {bandRect ? (
          <div
            className="pointer-events-none absolute z-20 border border-[#f28b82] bg-[#f28b82]/20"
            style={{ left: bandRect.left, top: bandRect.top, width: bandRect.width, height: bandRect.height }}
          />
        ) : null}
      </div>

      {menu ? (
        <div
          ref={menuRef}
          className="fixed z-[3000] min-w-[220px] rounded-md border border-[#cccccc] bg-white py-1 text-[12px] text-[#222] shadow-lg"
          onClick={(event) => event.stopPropagation()}
          onContextMenu={(event) => event.preventDefault()}
        >
          <MenuItem onClick={() => run('undo')} shortcut="Ctrl+Z">되돌리기</MenuItem>
          <MenuItem onClick={() => run('redo')} shortcut="Ctrl+Y">재실행</MenuItem>
          <div className="my-1 h-px bg-[#e8e8e8]" />
          <div className="px-3 py-1.5 text-[11px] text-slate-500">{selectionHeaderText(menuIndices)}</div>
          <div className="my-1 h-px bg-[#e8e8e8]" />
          <MenuItem disabled={!menuIndices.length} onClick={() => run('copy', { indices: menuIndices })}>
            {selectionActionLabel('복사', menuIndices)}
          </MenuItem>
          <MenuItem disabled={!menuIndices.length} onClick={() => run('cut', { indices: menuIndices })}>
            {selectionActionLabel('잘라내기', menuIndices)}
          </MenuItem>
          <MenuItem disabled={!menuIndices.length} onClick={() => run('exportImages', { indices: menuIndices })}>
            {selectionActionLabel('이미지로 저장', menuIndices, '를 ')}
          </MenuItem>
          <MenuItem disabled={!menuIndices.length} onClick={() => run('exportPdf', { indices: menuIndices })}>
            {selectionActionLabel('새 파일로 저장', menuIndices, '를 ')}
          </MenuItem>
          <div className="my-1 h-px bg-[#e8e8e8]" />
          <MenuItem disabled={!menuIndices.length} onClick={() => run('delete', { indices: menuIndices })}>
            {selectionActionLabel('삭제', menuIndices)}
          </MenuItem>
          <MenuItem disabled={!menuIndices.length} onClick={() => run('rotate', { indices: menuIndices, degrees: 90 })}>
            {selectionActionLabel('시계 방향 회전', menuIndices)}
          </MenuItem>
          <MenuItem disabled={!menuIndices.length} onClick={() => run('rotate', { indices: menuIndices, degrees: -90 })}>
            {selectionActionLabel('반시계 방향 회전', menuIndices)}
          </MenuItem>
          <div className="my-1 h-px bg-[#e8e8e8]" />
          <div className="px-3 py-1.5 text-[11px] text-slate-500">이 위치에 삽입 (페이지 {insertAt} 앞)</div>
          <MenuItem
            disabled={clipboardCount <= 0}
            onClick={() => run('paste', { targetIndex: menu.insertIndex })}
          >
            {clipboardCount > 0 ? `여기에 ${clipboardCount}페이지 붙여넣기` : '여기에 붙여넣기'}
          </MenuItem>
          <MenuItem onClick={() => run('insertBlank', { targetIndex: menu.insertIndex })}>
            {`빈 페이지 삽입 (페이지 ${insertAt} 앞)`}
          </MenuItem>
          <MenuItem onClick={() => run('insertFiles', { targetIndex: menu.insertIndex })}>
            {`파일 삽입 (페이지 ${insertAt} 앞)`}
          </MenuItem>
          <div className="my-1 h-px bg-[#e8e8e8]" />
          <MenuItem disabled={!menuIndices.length} onClick={() => run('ocr', { indices: menuIndices })}>
            {ocrLabel(menuIndices)}
          </MenuItem>
          <MenuItem disabled={!pageCount} onClick={() => run('ocrAll')}>
            전체페이지 OCR 실행
          </MenuItem>
          <div className="my-1 h-px bg-[#e8e8e8]" />
          <MenuItem disabled={!menuIndices.length} onClick={() => run('pii', { indices: menuIndices })}>
            {scopedLabel('개인정보 제거', menuIndices)}
          </MenuItem>
          <MenuItem disabled={!pageCount} onClick={() => run('piiAll')}>
            전체 페이지 개인정보 제거
          </MenuItem>
          <div className="my-1 h-px bg-[#e8e8e8]" />
          <MenuItem disabled={!menuIndices.length} onClick={() => run('print', { indices: menuIndices })}>
            {scopedLabel('인쇄', menuIndices)}
          </MenuItem>
          <MenuItem disabled={!pageCount} onClick={() => run('printAll')}>
            전체 페이지 인쇄
          </MenuItem>
        </div>
      ) : null}
    </aside>
  );
}

function MenuItem({ children, disabled, onClick, shortcut }) {
  return (
    <button
      type="button"
      disabled={disabled}
      className="flex w-full items-center gap-6 px-3 py-1.5 text-left hover:bg-[#f0f0f0] disabled:cursor-default disabled:text-slate-400 disabled:hover:bg-transparent"
      onClick={onClick}
    >
      <span>{children}</span>
      {shortcut ? <span className="ml-auto text-[11px] text-slate-400">{shortcut}</span> : null}
    </button>
  );
}

/** 원본 _DropIndicatorOverlay 와 같은 삽입 표시선(양 끝 눈금 포함). */
function DropLine({ className = 'absolute left-0 right-0 top-0' }) {
  return (
    <div className={`pointer-events-none z-10 h-[2px] bg-[#f28b82] ${className}`}>
      <span className="absolute -top-[5px] left-0 h-[12px] w-[2px] bg-[#f28b82]" />
      <span className="absolute -top-[5px] right-0 h-[12px] w-[2px] bg-[#f28b82]" />
    </div>
  );
}
