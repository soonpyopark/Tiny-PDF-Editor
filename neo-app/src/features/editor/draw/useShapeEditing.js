import { useEffect, useRef, useState } from 'react';
import { moveInk } from './inkPick.js';
import { moveGeom } from './shapeMath.js';

/**
 * 도형·잉크 선택/편집 컨트롤러.
 *
 * - 도형은 PDF 표준 주석으로 들어가 쪽 그림에 함께 그려진다. 이 훅은 목록을 가져와 클릭·선택에 쓰고,
 *   만들기·고치기·지우기를 엔진에 한 줄(queue)로 보내 순서가 뒤바뀌지 않게 한다.
 * - 고치면 주석이 새로 만들어져 id 가 바뀐다. 아직 대기 중인 요청이 옛 id 를 들고 있어도 되도록 옛 id → 새 id 를 기억한다.
 * - 올가미로 여러 항목을 고르면 selection 배열로 옮기기·Delete 를 한꺼번에 한다.
 * - 모양(색·굵기 …) 바꾸기는 항목이 하나일 때만 잠깐 모아서 한 번에 보낸다.
 * - 텍스트 상자의 글은 확정(commitText)할 때 엔진에 반영한다.
 */

const PATCH_DELAY_MS = 350;

/** @typedef {{ pageIndex: number, id: number, kind: 'shape' | 'ink' }} SelItem */

function asItem(next) {
  if (!next) return null;
  return {
    pageIndex: next.pageIndex,
    id: next.id,
    kind: next.kind === 'ink' ? 'ink' : 'shape',
  };
}

export function useShapeEditing(ctxValue) {
  const ctx = useRef(ctxValue);
  ctx.current = ctxValue;
  const { doc, pageIndex, enabled } = ctxValue;

  const [shapes, setShapes] = useState(/** @type {Record<number, any[]>} */ ({}));
  const [inks, setInks] = useState(/** @type {Record<number, any[]>} */ ({}));
  const cacheRef = useRef({
    doc: null,
    map: /** @type {Record<number, any[]>} */ ({}),
    inks: /** @type {Record<number, any[]>} */ ({}),
  });
  /** @type {SelItem[]} */
  const [selection, setSelectionState] = useState([]);
  const selectionRef = useRef(selection);
  const [textEdit, setTextEditState] = useState(/** @type {null | any} */ (null));
  const textEditRef = useRef(textEdit);
  const [shown, setShown] = useState(/** @type {null | { id: number, patch: any }} */ (null));
  const pendingRef = useRef(/** @type {null | { pageIndex: number, id: number, patch: any }} */ (null));
  const timerRef = useRef(0);
  const queueRef = useRef(Promise.resolve());
  const busyRef = useRef(0);
  const renamedRef = useRef(new Map());

  function setSelection(next) {
    const list = (Array.isArray(next) ? next : next ? [next] : []).map(asItem).filter(Boolean);
    selectionRef.current = list;
    setSelectionState(list);
  }

  function setTextEdit(next) {
    textEditRef.current = next;
    setTextEditState(next);
  }

  function enqueue(fn) {
    busyRef.current += 1;
    const job = queueRef.current
      .then(fn)
      .catch((err) => {
        ctx.current.setError(err instanceof Error ? err.message : '도형을 처리하지 못했습니다.');
      })
      .finally(() => {
        busyRef.current -= 1;
      });
    queueRef.current = job;
    return job;
  }

  const api = (name, body) => ctx.current.api(name, body);

  function resolveId(id) {
    let current = id;
    for (let i = 0; i < 20 && renamedRef.current.has(current); i += 1) current = renamedRef.current.get(current);
    return current;
  }

  function remapSelection(oldId, nextItem) {
    const list = selectionRef.current;
    if (!list.some((item) => item.id === oldId)) return;
    setSelection(list.map((item) => (item.id === oldId ? { ...item, ...nextItem, id: nextItem.id } : item)));
  }

  function invalidatePage(index) {
    if (cacheRef.current.doc) {
      delete cacheRef.current.map[index];
      delete cacheRef.current.inks[index];
    }
  }

  // ------------------------------------------------------------------ 쪽에 있는 도형·잉크 목록 (클릭해서 고르기용)
  useEffect(() => {
    if (!enabled || !doc.open || doc.pageCount < 1) {
      cacheRef.current = { doc: null, map: {}, inks: {} };
      setShapes({});
      setInks({});
      return undefined;
    }
    if (cacheRef.current.doc !== doc) cacheRef.current = { doc, map: {}, inks: {} };
    const cache = cacheRef.current;
    const from = Math.max(0, pageIndex - 2);
    const to = Math.min(doc.pageCount - 1, pageIndex + 3);
    const missing = [];
    for (let i = from; i <= to; i += 1) {
      if (!cache.map[i] || !cache.inks[i]) missing.push(i);
    }
    const publish = () => {
      setShapes({ ...cache.map });
      setInks({ ...cache.inks });
      if (busyRef.current !== 0) return;
      const kept = selectionRef.current.filter((sel) => {
        const shapesOnPage = cache.map[sel.pageIndex];
        const inksOnPage = cache.inks[sel.pageIndex];
        if (!shapesOnPage || !inksOnPage) return true;
        const list = sel.kind === 'ink' ? inksOnPage : shapesOnPage;
        return list.some((item) => item.id === sel.id);
      });
      if (kept.length !== selectionRef.current.length) setSelection(kept);
    };
    if (!missing.length) {
      publish();
      return undefined;
    }
    let cancelled = false;
    (async () => {
      for (const index of missing) {
        const [shapeResult, inkResult] = await Promise.all([
          ctx.current.api('pdf.shapeList', { pageIndex: index }),
          ctx.current.api('pdf.inkList', { pageIndex: index }),
        ]);
        if (cancelled || cacheRef.current !== cache) return;
        cache.map[index] = shapeResult.items || [];
        cache.inks[index] = inkResult.items || [];
      }
      if (!cancelled && cacheRef.current === cache) publish();
    })().catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [doc, pageIndex, enabled]);

  useEffect(() => {
    if (!pendingRef.current && busyRef.current === 0) setShown(null);
  }, [shapes]);

  // ------------------------------------------------------------------ 만들기 / 고치기 / 지우기
  function create(index, kind, geom, params, { select: doSelect = false } = {}) {
    return enqueue(async () => {
      const result = await api('pdf.shapeAdd', { pageIndex: index, kind, ...geom, params });
      await ctx.current.refreshPage(result.doc, index);
      if (doSelect) setSelection([{ pageIndex: index, id: result.shapeId, kind: 'shape' }]);
      return result.shapeId;
    });
  }

  function update(index, id, { geom, params } = {}) {
    return enqueue(async () => {
      const shapeId = resolveId(id);
      const result = await api('pdf.shapeUpdate', { pageIndex: index, shapeId, ...(geom || {}), params });
      if (result.changed) {
        renamedRef.current.set(shapeId, result.newId);
        remapSelection(shapeId, { pageIndex: index, id: result.newId, kind: 'shape' });
        invalidatePage(index);
        await ctx.current.refreshPage(result.doc, index);
      } else {
        setShown(null);
      }
      return result.newId;
    });
  }

  function updateInk(index, id, strokes) {
    return enqueue(async () => {
      const inkId = resolveId(id);
      const result = await api('pdf.inkUpdate', { pageIndex: index, inkId, strokes });
      if (result.changed) {
        renamedRef.current.set(inkId, result.newId);
        remapSelection(inkId, { pageIndex: index, id: result.newId, kind: 'ink' });
        invalidatePage(index);
        await ctx.current.refreshPage(result.doc, index);
      }
      return result.newId;
    });
  }

  /** 선택(하나 또는 여러 개)을 같은 양만큼 옮긴다. */
  function moveSelection(dx, dy, ptW, ptH, targets = selectionRef.current) {
    const list = Array.isArray(targets) ? targets : [];
    if (!list.length) return Promise.resolve();
    flushPatch();
    return enqueue(async () => {
      let lastDoc = null;
      const pages = new Set();
      const nextSelection = [];
      for (const target of list) {
        const index = target.pageIndex;
        pages.add(index);
        if (target.kind === 'ink') {
          const ink = (cacheRef.current.inks[index] || inks[index] || []).find((item) => item.id === target.id);
          if (!ink) {
            nextSelection.push(target);
            continue;
          }
          const { strokes } = moveInk(ink, dx, dy, ptW, ptH);
          const inkId = resolveId(target.id);
          const result = await api('pdf.inkUpdate', { pageIndex: index, inkId, strokes });
          lastDoc = result.doc;
          if (result.changed) {
            renamedRef.current.set(inkId, result.newId);
            nextSelection.push({ pageIndex: index, id: result.newId, kind: 'ink' });
          } else {
            nextSelection.push(target);
          }
        } else {
          const shape = (cacheRef.current.map[index] || shapes[index] || []).find((item) => item.id === target.id);
          if (!shape) {
            nextSelection.push(target);
            continue;
          }
          const geom = moveGeom(shape, dx, dy, ptW, ptH);
          const shapeId = resolveId(target.id);
          const result = await api('pdf.shapeUpdate', { pageIndex: index, shapeId, ...geom });
          lastDoc = result.doc;
          if (result.changed) {
            renamedRef.current.set(shapeId, result.newId);
            nextSelection.push({ pageIndex: index, id: result.newId, kind: 'shape' });
          } else {
            nextSelection.push(target);
          }
        }
      }
      setSelection(nextSelection);
      for (const index of pages) invalidatePage(index);
      if (lastDoc) {
        for (const index of pages) await ctx.current.refreshPage(lastDoc, index);
      }
    });
  }

  function remove(targets = selectionRef.current) {
    const list = (Array.isArray(targets) ? targets : targets ? [targets] : []).map(asItem).filter(Boolean);
    if (!list.length) return Promise.resolve();
    flushPatch();
    setSelection([]);
    return enqueue(async () => {
      let lastDoc = null;
      const pages = new Set();
      for (const target of list) {
        pages.add(target.pageIndex);
        const result =
          target.kind === 'ink'
            ? await api('pdf.inkDelete', { pageIndex: target.pageIndex, inkId: resolveId(target.id) })
            : await api('pdf.shapeDelete', { pageIndex: target.pageIndex, shapeId: resolveId(target.id) });
        lastDoc = result.doc;
      }
      for (const index of pages) invalidatePage(index);
      if (lastDoc) {
        for (const index of pages) await ctx.current.refreshPage(lastDoc, index);
      }
    });
  }

  // ------------------------------------------------------------------ 선택 / 모양 바꾸기
  function select(next) {
    flushPatch();
    setSelection(next ? [next] : []);
  }

  function selectMany(items) {
    flushPatch();
    setSelection(items || []);
  }

  function flushPatch() {
    window.clearTimeout(timerRef.current);
    timerRef.current = 0;
    const job = pendingRef.current;
    if (!job) return;
    pendingRef.current = null;
    void update(job.pageIndex, job.id, { params: job.patch });
  }

  function patchSelected(patch) {
    const sel = selectionRef.current.length === 1 ? selectionRef.current[0] : null;
    if (!sel || sel.kind === 'ink') return;
    const merged = pendingRef.current && pendingRef.current.id === sel.id ? { ...pendingRef.current.patch, ...patch } : patch;
    pendingRef.current = { pageIndex: sel.pageIndex, id: sel.id, patch: merged };
    setShown((prev) => ({ id: sel.id, patch: { ...(prev && prev.id === sel.id ? prev.patch : {}), ...patch } }));
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(flushPatch, PATCH_DELAY_MS);
  }

  function beginText({ pageIndex: index, id = null, rect, params, text = '' }) {
    flushPatch();
    void commitText();
    setTextEdit({ pageIndex: index, id, rect, params, text, original: text });
  }

  function setTextValue(text) {
    const current = textEditRef.current;
    if (current) setTextEdit({ ...current, text });
  }

  function commitText() {
    const current = textEditRef.current;
    if (!current) return Promise.resolve();
    setTextEdit(null);
    if (current.id == null) {
      if (!current.text.trim()) return Promise.resolve();
      return create(current.pageIndex, 'text', { rect: current.rect }, { ...current.params, text: current.text }, { select: false });
    }
    if (current.text === current.original) return Promise.resolve();
    return update(current.pageIndex, current.id, { params: { text: current.text } });
  }

  function cancelText() {
    setTextEdit(null);
  }

  async function commit() {
    await commitText();
    flushPatch();
    await queueRef.current;
  }

  useEffect(() => {
    if (enabled) return;
    void commit();
    setSelection([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  useEffect(() => {
    if (!doc.open) {
      setSelection([]);
      setTextEdit(null);
      renamedRef.current.clear();
    }
  }, [doc.open]);

  useEffect(() => {
    if (!enabled) return undefined;
    function onKeyDown(event) {
      const el = event.target;
      if (el instanceof HTMLTextAreaElement) return;
      if (el instanceof HTMLInputElement && !['range', 'checkbox', 'radio', 'button', 'color'].includes(el.type)) return;
      if (!selectionRef.current.length) return;
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        event.stopImmediatePropagation();
        void remove();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        select(null);
      }
    }
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  const selected = selection.length === 1 ? selection[0] : null;
  const selectedKind = selected?.kind === 'ink' ? 'ink' : 'shape';
  const selectedInk =
    selected && selectedKind === 'ink'
      ? (inks[selected.pageIndex] || []).find((item) => item.id === selected.id) || null
      : null;
  const selectedBase =
    selected && selectedKind === 'shape'
      ? (shapes[selected.pageIndex] || []).find((item) => item.id === selected.id) || null
      : null;
  const selectedShape =
    selectedBase && shown && shown.id === selectedBase.id ? { ...selectedBase, params: { ...selectedBase.params, ...shown.patch } } : selectedBase;

  return {
    enabled,
    shapes,
    inks,
    selected,
    selection,
    selectedShape,
    selectedInk,
    textEdit,
    create,
    update,
    updateInk,
    moveSelection,
    remove,
    select,
    selectMany,
    patchSelected,
    beginText,
    setTextValue,
    commitText,
    cancelText,
    commit,
  };
}
