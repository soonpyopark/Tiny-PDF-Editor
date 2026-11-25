import { useEffect, useRef, useState } from 'react';

/**
 * 도형(선·화살표·사각형·타원·다각형·클라우드·폴리라인·텍스트 상자) 컨트롤러.
 *
 * - 도형은 PDF 표준 주석으로 들어가 쪽 그림에 함께 그려진다. 이 훅은 목록을 가져와 클릭·선택에 쓰고,
 *   만들기·고치기·지우기를 엔진에 한 줄(queue)로 보내 순서가 뒤바뀌지 않게 한다.
 * - 고치면 주석이 새로 만들어져 id 가 바뀐다. 아직 대기 중인 요청이 옛 id 를 들고 있어도 되도록 옛 id → 새 id 를 기억한다.
 * - 모양(색·굵기 …) 바꾸기는 잠깐 모아서 한 번에 보낸다(슬라이더를 끌 때 되돌리기 단계가 쌓이지 않게).
 * - 텍스트 상자의 글은 확정(commitText)할 때 엔진에 반영한다.
 */

const PATCH_DELAY_MS = 350;

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
  /** @type {null | { pageIndex: number, id: number, kind?: 'shape' | 'ink' }} */
  const [selected, setSelectedState] = useState(null);
  const selectedRef = useRef(selected);
  const [textEdit, setTextEditState] = useState(/** @type {null | any} */ (null));
  const textEditRef = useRef(textEdit);
  const [shown, setShown] = useState(/** @type {null | { id: number, patch: any }} */ (null));
  const pendingRef = useRef(/** @type {null | { pageIndex: number, id: number, patch: any }} */ (null));
  const timerRef = useRef(0);
  const queueRef = useRef(Promise.resolve());
  const busyRef = useRef(0);
  const renamedRef = useRef(new Map());

  function setSelected(next) {
    selectedRef.current = next;
    setSelectedState(next);
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
      // 목록에 없는 항목을 가리키고 있으면(되돌리기 등으로 사라짐) 선택을 푼다.
      const sel = selectedRef.current;
      if (!sel || busyRef.current !== 0) return;
      const shapesOnPage = cache.map[sel.pageIndex];
      const inksOnPage = cache.inks[sel.pageIndex];
      if (!shapesOnPage || !inksOnPage) return;
      const kind = sel.kind === 'ink' ? 'ink' : 'shape';
      const list = kind === 'ink' ? inksOnPage : shapesOnPage;
      if (!list.some((item) => item.id === sel.id)) setSelected(null);
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

  // 서버에서 새 목록이 오면 임시로 보여 주던 모양 값을 걷는다.
  useEffect(() => {
    if (!pendingRef.current && busyRef.current === 0) setShown(null);
  }, [shapes]);

  // ------------------------------------------------------------------ 만들기 / 고치기 / 지우기
  function create(index, kind, geom, params, { select = false } = {}) {
    return enqueue(async () => {
      const result = await api('pdf.shapeAdd', { pageIndex: index, kind, ...geom, params });
      await ctx.current.refreshPage(result.doc, index);
      if (select) setSelected({ pageIndex: index, id: result.shapeId, kind: 'shape' });
      return result.shapeId;
    });
  }

  function update(index, id, { geom, params } = {}) {
    return enqueue(async () => {
      const shapeId = resolveId(id);
      const result = await api('pdf.shapeUpdate', { pageIndex: index, shapeId, ...(geom || {}), params });
      if (result.changed) {
        renamedRef.current.set(shapeId, result.newId);
        if (selectedRef.current && selectedRef.current.id === shapeId) {
          setSelected({ pageIndex: index, id: result.newId, kind: 'shape' });
        }
        await ctx.current.refreshPage(result.doc, index);
      } else {
        setShown(null);
      }
      return result.newId;
    });
  }

  function remove(target = selectedRef.current) {
    if (!target) return Promise.resolve();
    flushPatch();
    const { pageIndex: index, id } = target;
    const kind = target.kind === 'ink' ? 'ink' : 'shape';
    if (selectedRef.current && selectedRef.current.id === id) setSelected(null);
    return enqueue(async () => {
      const result =
        kind === 'ink'
          ? await api('pdf.inkDelete', { pageIndex: index, inkId: id })
          : await api('pdf.shapeDelete', { pageIndex: index, shapeId: resolveId(id) });
      // 같은 쪽 캐시를 비워 다음 목록 요청이 새 내용을 받게 한다.
      if (cacheRef.current.doc) {
        delete cacheRef.current.map[index];
        delete cacheRef.current.inks[index];
      }
      await ctx.current.refreshPage(result.doc, index);
    });
  }

  // ------------------------------------------------------------------ 선택 / 모양 바꾸기
  function select(next) {
    flushPatch();
    setSelected(next);
  }

  function flushPatch() {
    window.clearTimeout(timerRef.current);
    timerRef.current = 0;
    const job = pendingRef.current;
    if (!job) return;
    pendingRef.current = null;
    void update(job.pageIndex, job.id, { params: job.patch });
  }

  /** 선택한 도형의 모양을 바꾼다(엔진 모양 한 부분). 잠깐 모아서 한 번에 보낸다. 잉크 선택에는 쓰지 않는다. */
  function patchSelected(patch) {
    const sel = selectedRef.current;
    if (!sel || sel.kind === 'ink') return;
    const merged = pendingRef.current && pendingRef.current.id === sel.id ? { ...pendingRef.current.patch, ...patch } : patch;
    pendingRef.current = { pageIndex: sel.pageIndex, id: sel.id, patch: merged };
    setShown((prev) => ({ id: sel.id, patch: { ...(prev && prev.id === sel.id ? prev.patch : {}), ...patch } }));
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(flushPatch, PATCH_DELAY_MS);
  }

  // ------------------------------------------------------------------ 텍스트 상자 글 입력
  /** 글 입력을 연다. id 가 없으면 새 상자(확정할 때 만들어짐), 있으면 기존 상자의 글 고치기. */
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

  // 저장·되돌리기·닫기 전에 부른다: 입력 중인 글과 모아 둔 모양 바꾸기를 모두 반영하고 기다린다.
  async function commit() {
    await commitText();
    flushPatch();
    await queueRef.current;
  }

  // 그리기 끝내기·도구 바꾸기 등으로 도형 편집이 꺼지면 선택·입력을 정리한다.
  useEffect(() => {
    if (enabled) return;
    void commit();
    setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // 쪽이 바뀌거나 다른 문서가 열리면 선택을 푼다.
  useEffect(() => {
    if (!doc.open) {
      setSelected(null);
      setTextEdit(null);
      renamedRef.current.clear();
    }
  }, [doc.open]);

  // Delete 로 지우기, Esc 로 선택 풀기 (선택이 있을 때만; 없으면 Esc 는 그리기 끝내기로 간다).
  useEffect(() => {
    if (!enabled) return undefined;
    function onKeyDown(event) {
      const el = event.target;
      if (el instanceof HTMLTextAreaElement) return;
      if (el instanceof HTMLInputElement && !['range', 'checkbox', 'radio', 'button', 'color'].includes(el.type)) return;
      if (!selectedRef.current) return;
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
    selectedShape,
    selectedInk,
    textEdit,
    create,
    update,
    remove,
    select,
    patchSelected,
    beginText,
    setTextValue,
    commitText,
    cancelText,
    commit,
  };
}
