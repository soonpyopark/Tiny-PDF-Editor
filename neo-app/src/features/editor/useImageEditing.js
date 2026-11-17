import { useEffect, useRef, useState } from 'react';
import { clampRectToPage } from './imageBoxMath.js';
import {
  alignRect,
  applyLocalPatch,
  moveGroup,
  needsEngine,
  parsePageRange,
  pasteRect,
  presetRect,
  rectAfterCrop,
  rectAfterRotate,
  rectSize,
  setHeight,
  setPosition,
  setWidth,
  snapMoveRect,
  snapTargets,
  visibleAspect,
} from './imageEditMath.js';

// 앱 전체(탭·문서 사이)에서 같이 쓰는 이미지 복사본. 문서가 달라도 붙여 넣을 수 있다.
let imageClipboard = /** @type {null | { items: any[], pageIndex: number, pasteCount: number }} */ (null);
// 마지막으로 복사한 것이 쪽인지 이미지인지. 붙여넣기가 어느 쪽을 따를지 정한다.
let lastCopyKind = /** @type {'page' | 'image'} */ ('page');

export function noteCopyKind(kind) {
  lastCopyKind = kind;
}

const SNAP_PX = 6;
const rectEqual = (a, b) => a.every((value, index) => Math.abs(value - b[index]) < 1e-3);
const isDirty = (item) => Boolean(item.rectDirty || item.paramsDirty);
const asDataUrl = (png) => `data:image/png;base64,${png}`;

function pageOf(getPageBox, pageIndex) {
  return getPageBox(pageIndex);
}

/**
 * 이미지 넣기·다시 고치기 컨트롤러.
 *
 * 세션(items) = 지금 고르고 있는(선택된) 이미지들. 새로 넣는 것(id=null, token)과 이미 넣은 것(id)이 섞일 수 있다.
 * 고르는 동안 이미 넣은 이미지는 쪽 그림에서 걷어 내고(engine imageLift) 오버레이가 대신 보여 주며,
 * 확정(commit)할 때 바뀐 것만 PDF 에 반영한다. 반영 전에는 PDF 가 바뀌지 않는다.
 * 엔진 호출은 모두 한 줄(queue)로 처리해 순서가 뒤바뀌지 않게 한다.
 */
export function useImageEditing(ctxValue) {
  const ctx = useRef(ctxValue);
  ctx.current = ctxValue;

  const [items, setItemsState] = useState(/** @type {any[]} */ ([]));
  const itemsRef = useRef(items);
  const [stamps, setStamps] = useState(/** @type {Record<number, any[]>} */ ({}));
  const stampCache = useRef({ doc: null, map: /** @type {Record<number, any[]>} */ ({}) });
  const [guides, setGuides] = useState(/** @type {null | { pageIndex: number, lines: any[] }} */ (null));
  const [eyedrop, setEyedrop] = useState(false);
  const queueRef = useRef(Promise.resolve());
  const gestureRef = useRef(/** @type {any} */ (null));
  const draggingRef = useRef(false);
  const counterRef = useRef(0);

  function setItems(updater) {
    const next = typeof updater === 'function' ? updater(itemsRef.current) : updater;
    itemsRef.current = next;
    setItemsState(next);
  }

  function enqueue(fn) {
    const job = queueRef.current.then(fn).catch((err) => {
      ctx.current.setError(err instanceof Error ? err.message : '이미지를 처리하지 못했습니다.');
    });
    queueRef.current = job;
    return job;
  }

  const api = (name, body) => ctx.current.api(name, body);
  const pageBox = (pageIndex) => pageOf(ctx.current.getPageBox, pageIndex);

  // ------------------------------------------------------------------ 쪽에 이미 있는 이미지 목록 (클릭해서 고르기용)
  const { doc, pageIndex } = ctxValue;
  useEffect(() => {
    if (!doc.open || doc.pageCount < 1) {
      stampCache.current = { doc: null, map: {} };
      setStamps({});
      return undefined;
    }
    if (stampCache.current.doc !== doc) stampCache.current = { doc, map: {} };
    const cache = stampCache.current;
    const from = Math.max(0, pageIndex - 2);
    const to = Math.min(doc.pageCount - 1, pageIndex + 3);
    const missing = [];
    for (let i = from; i <= to; i += 1) if (!cache.map[i]) missing.push(i);
    if (!missing.length) {
      setStamps({ ...cache.map });
      return undefined;
    }
    let cancelled = false;
    (async () => {
      for (const index of missing) {
        const result = await ctx.current.api('pdf.imageList', { pageIndex: index });
        if (cancelled || stampCache.current !== cache) return;
        cache.map[index] = result.items || [];
      }
      if (!cancelled && stampCache.current === cache) setStamps({ ...cache.map });
    })().catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [doc, pageIndex]);

  function invalidateStamps() {
    stampCache.current = { doc: null, map: {} };
  }

  // ------------------------------------------------------------------ 확정 / 취소 / 삭제
  async function commitInner() {
    const current = itemsRef.current;
    if (!current.length) return [];
    const results = [];
    const committedKeys = new Set();
    let lastDoc = null;
    let changed = false;
    try {
      for (const item of current.filter((it) => it.id == null)) {
        const result = await api('pdf.imageCommit', {
          pageIndex: item.pageIndex,
          token: item.token,
          rect: item.rect,
          params: item.params,
        });
        lastDoc = result.doc;
        changed = true;
        committedKeys.add(item.key);
        results.push({ pageIndex: item.pageIndex, id: result.id });
      }
      const existing = current.filter((it) => it.id != null);
      const dirty = existing.filter(isDirty);
      const newIds = new Map();
      if (dirty.length) {
        const result = await api('pdf.imageUpdate', {
          updates: dirty.map((it) => ({ pageIndex: it.pageIndex, id: it.id, rect: it.rect, params: it.params })),
        });
        lastDoc = result.doc;
        changed = true;
        for (const row of result.results || []) newIds.set(row.id, row.newId);
      }
      if (!changed && existing.length) {
        await api('pdf.imageLift', { targets: existing.map((it) => ({ pageIndex: it.pageIndex, id: it.id })), lifted: false });
      }
      for (const it of existing) results.push({ pageIndex: it.pageIndex, id: newIds.get(it.id) ?? it.id });
      invalidateStamps();
      // 쪽 그림을 먼저 새로 그린 뒤 오버레이를 걷는다. 그래야 중간에 이미지가 사라져 보이지 않는다.
      for (const index of new Set(current.map((it) => it.pageIndex))) {
        await ctx.current.refreshPage(lastDoc ?? ctx.current.docRef.current, index);
      }
      setItems([]);
      setEyedrop(false);
    } catch (err) {
      setItems((prev) => prev.filter((it) => !committedKeys.has(it.key)));
      throw err;
    }
    return results;
  }

  function commit() {
    return enqueue(commitInner);
  }

  async function discardInner() {
    const current = itemsRef.current;
    if (!current.length) return;
    const existing = current.filter((it) => it.id != null);
    setItems([]);
    setEyedrop(false);
    if (existing.length) {
      await api('pdf.imageLift', { targets: existing.map((it) => ({ pageIndex: it.pageIndex, id: it.id })), lifted: false });
      for (const index of new Set(existing.map((it) => it.pageIndex))) {
        await ctx.current.refreshPage(ctx.current.docRef.current, index);
      }
    }
  }

  function discard() {
    return enqueue(discardInner);
  }

  /** 문서가 바뀌어 세션이 의미 없어질 때(새 문서 열기 등). 엔진에 알리지 않고 비운다. */
  function reset() {
    itemsRef.current = [];
    setItemsState([]);
    setEyedrop(false);
    invalidateStamps();
  }

  function deleteSelected() {
    return enqueue(async () => {
      const current = itemsRef.current;
      if (!current.length) return;
      const existing = current.filter((it) => it.id != null);
      if (!existing.length) {
        setItems([]);
        return;
      }
      const result = await api('pdf.imageDelete', {
        targets: existing.map((it) => ({ pageIndex: it.pageIndex, id: it.id })),
      });
      invalidateStamps();
      for (const index of new Set(existing.map((it) => it.pageIndex))) {
        await ctx.current.refreshPage(result.doc, index);
      }
      setItems([]);
    });
  }

  // ------------------------------------------------------------------ 새로 넣기 / 고르기
  function newItem(result, pageIdx, extra = {}) {
    counterRef.current += 1;
    return {
      key: `n${counterRef.current}`,
      pageIndex: pageIdx,
      id: null,
      token: result.token,
      rect: result.rect,
      page: result.page,
      params: result.params,
      preview: result.preview,
      rectDirty: true,
      paramsDirty: true,
      ...extra,
    };
  }

  /** 클립보드/파일/드롭한 이미지를 올려 놓는다. opts: { fromClipboard, image, pageIndex, centerAt, rect, sizePt, params } */
  async function place(opts = {}) {
    if (!ctx.current.docRef.current.open) return;
    // 그리기를 끝내는 일(endDrawing)은 확정(commit)을 부르므로 줄 밖에서 먼저 한다. 줄 안에서 하면 서로 기다리며 멈춘다.
    if (ctx.current.drawOnRef.current) await ctx.current.endDrawing();
    return enqueue(async () => {
      ctx.current.setError('');
      await commitInner();
      const pageIdx = opts.pageIndex ?? ctx.current.pageIndexRef.current;
      const result = await api('pdf.imagePrepare', {
        pageIndex: pageIdx,
        fromClipboard: Boolean(opts.fromClipboard),
        image: opts.image,
        rect: opts.rect,
        sizePt: opts.sizePt,
        params: opts.params,
      });
      if (result.canceled) return;
      let rect = result.rect;
      if (opts.centerAt) {
        const { width, height } = rectSize(rect);
        rect = clampRectToPage(
          [opts.centerAt.x - width / 2, opts.centerAt.y - height / 2, opts.centerAt.x + width / 2, opts.centerAt.y + height / 2],
          result.page,
        );
      }
      setItems([newItem({ ...result, rect }, pageIdx)]);
    });
  }

  /** 이미 넣은 이미지를 클릭해 고른다. additive 면 기존 선택에 더한다(Shift+클릭). */
  function selectStamp(stamp, additive = false) {
    return enqueue(async () => {
      if (!additive) await commitInner();
      else if (itemsRef.current.some((it) => it.id === stamp.id)) return;
      const preview = await api('pdf.imagePreview', { pageIndex: stamp.pageIndex, id: stamp.id });
      const item = {
        key: `s${stamp.id}`,
        pageIndex: stamp.pageIndex,
        id: stamp.id,
        token: null,
        rect: stamp.rect,
        startRect: stamp.rect,
        page: pageBox(stamp.pageIndex),
        params: preview.params,
        startParams: preview.params,
        preview: preview.preview,
        rectDirty: false,
        paramsDirty: false,
      };
      setItems((prev) => [...prev, item]);
      await api('pdf.imageLift', { targets: [{ pageIndex: stamp.pageIndex, id: stamp.id }], lifted: true });
      await ctx.current.refreshPage(ctx.current.docRef.current, stamp.pageIndex);
    });
  }

  /** 현재 쪽의 이미지를 모두 고른다 (Ctrl+A). */
  function selectAllOnPage() {
    const index = ctx.current.pageIndexRef.current;
    const list = (stampCache.current.map[index] || []).filter((s) => !itemsRef.current.some((it) => it.id === s.id));
    return enqueue(async () => {
      for (const stamp of list) {
        const preview = await api('pdf.imagePreview', { pageIndex: stamp.pageIndex, id: stamp.id });
        setItems((prev) => [
          ...prev,
          {
            key: `s${stamp.id}`,
            pageIndex: stamp.pageIndex,
            id: stamp.id,
            token: null,
            rect: stamp.rect,
            startRect: stamp.rect,
            page: pageBox(stamp.pageIndex),
            params: preview.params,
            startParams: preview.params,
            preview: preview.preview,
            rectDirty: false,
            paramsDirty: false,
          },
        ]);
      }
      if (list.length) {
        await api('pdf.imageLift', { targets: list.map((s) => ({ pageIndex: s.pageIndex, id: s.id })), lifted: true });
        await ctx.current.refreshPage(ctx.current.docRef.current, index);
      }
    });
  }

  // ------------------------------------------------------------------ 이동·크기 (오버레이 드래그, 방향키, 숫자 입력)
  function markRects(map) {
    setItems((prev) =>
      prev.map((it) => {
        const rect = map.get(it.key);
        if (!rect) return it;
        const dirty = it.id == null ? true : !rectEqual(rect, it.startRect);
        return { ...it, rect, rectDirty: dirty };
      }),
    );
  }

  function beginGesture(key) {
    const current = itemsRef.current;
    const primary = current.find((it) => it.key === key);
    if (!primary) return;
    const group = current.filter((it) => it.pageIndex === primary.pageIndex && !it.params.lock);
    gestureRef.current = {
      key,
      pageIndex: primary.pageIndex,
      group: group.map((it) => it.key),
      starts: new Map(group.map((it) => [it.key, it.rect])),
      page: primary.page,
    };
    draggingRef.current = true;
  }

  function moveGesture(dx, dy, noSnap = false) {
    const g = gestureRef.current;
    if (!g) return;
    const starts = g.group.map((k) => g.starts.get(k));
    let moved = moveGroup(starts, dx, dy, g.page);
    let lines = [];
    if (!noSnap) {
      const bbox = [
        Math.min(...moved.map((r) => r[0])),
        Math.min(...moved.map((r) => r[1])),
        Math.max(...moved.map((r) => r[2])),
        Math.max(...moved.map((r) => r[3])),
      ];
      const others = (stampCache.current.map[g.pageIndex] || [])
        .filter((s) => !itemsRef.current.some((it) => it.id === s.id))
        .map((s) => s.rect);
      const threshold = SNAP_PX / Math.max(0.05, ctx.current.zoomRef.current);
      const snapped = snapMoveRect(bbox, snapTargets(g.page, others), threshold);
      moved = moveGroup(moved, snapped.rect[0] - bbox[0], snapped.rect[1] - bbox[1], g.page);
      lines = snapped.guides;
    }
    markRects(new Map(g.group.map((k, i) => [k, moved[i]])));
    setGuides(lines.length ? { pageIndex: g.pageIndex, lines } : null);
  }

  /** 핸들로 크기를 바꾼다(하나만). */
  function resizeTo(key, rect) {
    markRects(new Map([[key, rect]]));
  }

  function endGesture() {
    gestureRef.current = null;
    draggingRef.current = false;
    setGuides(null);
  }

  function nudgeSelected(key, step) {
    const current = itemsRef.current.filter((it) => !it.params.lock);
    if (!current.length) return;
    const map = new Map();
    const byPage = new Map();
    for (const it of current) byPage.set(it.pageIndex, [...(byPage.get(it.pageIndex) || []), it]);
    for (const [index, list] of byPage) {
      const page = pageBox(index);
      const dx = key === 'ArrowLeft' ? -step : key === 'ArrowRight' ? step : 0;
      const dy = key === 'ArrowUp' ? -step : key === 'ArrowDown' ? step : 0;
      const moved = moveGroup(list.map((it) => it.rect), dx, dy, page);
      list.forEach((it, i) => map.set(it.key, moved[i]));
    }
    markRects(map);
  }

  /** 첫 번째(마지막으로 고른) 이미지의 크기·위치를 숫자로. kind: width|height|x|y|preset|align */
  function transformPrimary(kind, value) {
    const current = itemsRef.current;
    const primary = current[current.length - 1];
    if (!primary || primary.params.lock) return;
    const aspect = visibleAspect(primary.params);
    const page = pageBox(primary.pageIndex);
    let next = primary.rect;
    if (kind === 'width') next = setWidth(primary.rect, aspect, page, value);
    else if (kind === 'height') next = setHeight(primary.rect, aspect, page, value);
    else if (kind === 'x') next = setPosition(primary.rect, page, value, NaN);
    else if (kind === 'y') next = setPosition(primary.rect, page, NaN, value);
    else if (kind === 'preset') next = presetRect(primary.rect, aspect, page, value, { width: primary.params.ow, height: primary.params.oh });
    markRects(new Map([[primary.key, next]]));
  }

  function alignSelected(how) {
    const map = new Map();
    for (const it of itemsRef.current) {
      if (it.params.lock) continue;
      map.set(it.key, alignRect(it.rect, pageBox(it.pageIndex), how));
    }
    markRects(map);
  }

  // ------------------------------------------------------------------ 모양 바꾸기 (투명도·배경·회전·자르기·색 보정)
  /** 고른 이미지 모두에 변경을 적용한다. patch 는 엔진 apply_patch 와 같은 모양. */
  function patchSelected(patch) {
    return enqueue(async () => {
      const updated = new Map();
      for (const it of itemsRef.current) {
        let params;
        let preview = it.preview;
        if (needsEngine(patch)) {
          const result = await api('pdf.imagePreview', {
            token: it.id == null ? it.token : undefined,
            pageIndex: it.pageIndex,
            id: it.id == null ? undefined : it.id,
            params: it.params,
            patch,
          });
          params = result.params;
          preview = result.preview;
        } else {
          params = applyLocalPatch(it.params, patch);
        }
        let rect = it.rect;
        const page = pageBox(it.pageIndex);
        if (patch.rotate) rect = rectAfterRotate(rect, page);
        else if (patch.crop || patch.cropReset) rect = rectAfterCrop(rect, it.params.crop, params.crop, page);
        // 보이는 그림 비율과 상자 비율이 어긋나지 않게 가로를 기준으로 다시 맞춘다.
        const aspect = visibleAspect(params);
        const size = rectSize(rect);
        if (Math.abs(size.width / size.height - aspect) > 1e-3) {
          const cx = (rect[0] + rect[2]) / 2;
          const cy = (rect[1] + rect[3]) / 2;
          const h = size.width / aspect;
          rect = clampRectToPage([cx - size.width / 2, cy - h / 2, cx + size.width / 2, cy + h / 2], page);
        }
        updated.set(it.key, { params, preview, rect });
      }
      setItems((prev) =>
        prev.map((it) => {
          const u = updated.get(it.key);
          if (!u) return it;
          const rectDirty = it.id == null ? true : !rectEqual(u.rect, it.startRect);
          const paramsDirty = it.id == null ? true : JSON.stringify(u.params) !== JSON.stringify(it.startParams);
          return { ...it, ...u, rectDirty, paramsDirty };
        }),
      );
    });
  }

  /** 스포이트: 이미지 위의 점(fx, fy 는 보이는 영역 안의 0~1 위치)의 색을 "투명하게 할 배경색"으로 쓴다. */
  function pickBackground(key, fx, fy) {
    return enqueue(async () => {
      const it = itemsRef.current.find((x) => x.key === key);
      if (!it) return;
      const plain = await api('pdf.imagePreview', {
        token: it.id == null ? it.token : undefined,
        pageIndex: it.pageIndex,
        id: it.id == null ? undefined : it.id,
        params: it.params,
        patch: { bg: { on: false } },
      });
      const img = new Image();
      img.src = asDataUrl(plain.preview);
      await img.decode();
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const g = canvas.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0);
      const [l, t, r, b] = it.params.crop;
      const ux = l + Math.min(1, Math.max(0, fx)) * (1 - l - r);
      const uy = t + Math.min(1, Math.max(0, fy)) * (1 - t - b);
      const px = Math.min(canvas.width - 1, Math.floor(ux * canvas.width));
      const py = Math.min(canvas.height - 1, Math.floor(uy * canvas.height));
      const [red, green, blue] = g.getImageData(px, py, 1, 1).data;
      setEyedrop(false);
      await patchInner({ bg: { on: true, color: [red, green, blue] } });
    });
  }

  async function patchInner(patch) {
    // enqueue 안에서 쓰는 patchSelected (큐 안에서 다시 큐에 넣으면 멈추므로 같은 일을 직접 한다)
    const updated = new Map();
    for (const it of itemsRef.current) {
      const result = await api('pdf.imagePreview', {
        token: it.id == null ? it.token : undefined,
        pageIndex: it.pageIndex,
        id: it.id == null ? undefined : it.id,
        params: it.params,
        patch,
      });
      updated.set(it.key, { params: result.params, preview: result.preview });
    }
    setItems((prev) =>
      prev.map((it) => {
        const u = updated.get(it.key);
        if (!u) return it;
        return { ...it, ...u, paramsDirty: it.id == null ? true : JSON.stringify(u.params) !== JSON.stringify(it.startParams) };
      }),
    );
  }

  // ------------------------------------------------------------------ 복사·잘라내기·붙여넣기·복제
  async function copyInner() {
    const current = itemsRef.current;
    if (!current.length) return false;
    const copied = [];
    for (const it of current) {
      const source = await api('pdf.imageSource', {
        pageIndex: it.pageIndex,
        id: it.id == null ? undefined : it.id,
        token: it.id == null ? it.token : undefined,
        params: it.params,
        rect: it.rect,
      });
      copied.push({
        image: source.image,
        params: it.params,
        rect: it.rect,
        sizePt: [it.rect[2] - it.rect[0], it.rect[3] - it.rect[1]],
      });
    }
    imageClipboard = { items: copied, pageIndex: current[0].pageIndex, pasteCount: 0 };
    lastCopyKind = 'image';
    return true;
  }

  function copySelected() {
    return enqueue(async () => {
      await copyInner();
    });
  }

  function cutSelected() {
    return enqueue(async () => {
      if (!(await copyInner())) return;
      const current = itemsRef.current;
      const existing = current.filter((it) => it.id != null);
      if (existing.length) {
        const result = await api('pdf.imageDelete', { targets: existing.map((it) => ({ pageIndex: it.pageIndex, id: it.id })) });
        invalidateStamps();
        for (const index of new Set(existing.map((it) => it.pageIndex))) {
          await ctx.current.refreshPage(result.doc, index);
        }
      }
      setItems([]);
    });
  }

  async function pasteInner() {
    if (!imageClipboard) return;
    await commitInner();
    const target = ctx.current.pageIndexRef.current;
    const page = pageBox(target);
    const clip = imageClipboard;
    const created = [];
    for (const entry of clip.items) {
      const rect = pasteRect(entry.rect, clip.pageIndex === target, clip.pasteCount, page);
      const result = await api('pdf.imagePrepare', {
        pageIndex: target,
        image: entry.image,
        params: entry.params,
        sizePt: entry.sizePt,
        rect,
      });
      created.push(newItem(result, target));
    }
    clip.pasteCount += 1;
    setItems(created);
  }

  function pasteClip() {
    return enqueue(pasteInner);
  }

  function duplicateSelected() {
    return enqueue(async () => {
      if (await copyInner()) await pasteInner();
    });
  }

  // ------------------------------------------------------------------ 다른 쪽에도 / 본문 글 아래로 / 굳히기 / 잠금
  /** pagesText: '' 또는 'all' 이면 모든 쪽, 아니면 "2-4, 7". 지금 쪽은 건너뛴다. */
  function applyToPages(pagesText) {
    return enqueue(async () => {
      const count = ctx.current.docRef.current.pageCount;
      const pages = !pagesText || pagesText === 'all' ? Array.from({ length: count }, (_, i) => i) : parsePageRange(pagesText, count);
      if (!pages.length) {
        ctx.current.setError('적용할 쪽 번호를 확인하세요. 예: 2-5, 8');
        return;
      }
      const results = await commitInner();
      if (!results.length) return;
      let result = null;
      for (const entry of results) {
        result = await api('pdf.imageApplyPages', { pageIndex: entry.pageIndex, id: entry.id, pages });
      }
      invalidateStamps();
      if (result) await ctx.current.applyDocResult(result, ctx.current.pageIndexRef.current);
    });
  }

  /** below=true 면 본문 글 아래로 보내 굳힌다. 굳힌 뒤에는 이미지로 고칠 수 없다. */
  function flatten(below) {
    return enqueue(async () => {
      const results = await commitInner();
      let result = null;
      for (const entry of results) {
        result = await api('pdf.imageFlatten', { pageIndex: entry.pageIndex, id: entry.id, below: Boolean(below) });
      }
      invalidateStamps();
      if (result) {
        for (const index of new Set(results.map((r) => r.pageIndex))) {
          await ctx.current.refreshPage(result.doc, index);
        }
      }
    });
  }

  // ------------------------------------------------------------------ 키보드·바깥 클릭
  const active = items.length > 0;
  const armedRef = useRef(false);
  useEffect(() => {
    if (!active || !ctx.current.active) return undefined;
    armedRef.current = false;
    const arm = window.setTimeout(() => {
      armedRef.current = true;
    }, 400);
    function onPointerDown(event) {
      if (!armedRef.current || draggingRef.current) return;
      const target = event.target;
      if (target instanceof Element && target.closest('[data-img-overlay="1"], [data-img-hit="1"]')) return;
      void commit();
    }
    function onKeyDown(event) {
      const typing =
        event.target instanceof HTMLTextAreaElement ||
        (event.target instanceof HTMLInputElement && !['range', 'checkbox', 'radio', 'button', 'color'].includes(event.target.type));
      if (typing) return;
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key;
      const swallow = () => {
        event.preventDefault();
        event.stopImmediatePropagation();
      };
      if (key === 'Enter') {
        swallow();
        void commit();
      } else if (key === 'Escape') {
        swallow();
        void discard();
      } else if (key === 'Delete' || key === 'Backspace') {
        swallow();
        void deleteSelected();
      } else if (key.startsWith('Arrow')) {
        if (key === 'ArrowLeft' || key === 'ArrowRight' || key === 'ArrowUp' || key === 'ArrowDown') {
          swallow();
          nudgeSelected(key, event.shiftKey ? 10 : 1);
        }
      } else if (mod && key.toLowerCase() === 'c') {
        swallow();
        void copySelected();
      } else if (mod && key.toLowerCase() === 'x') {
        swallow();
        void cutSelected();
      } else if (mod && key.toLowerCase() === 'd') {
        swallow();
        void duplicateSelected();
      } else if (mod && key.toLowerCase() === 'v' && imageClipboard && lastCopyKind === 'image') {
        swallow();
        void pasteClip();
      } else if (mod && key.toLowerCase() === 'a') {
        swallow();
        void selectAllOnPage();
      }
    }
    window.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('keydown', onKeyDown, true);
    return () => {
      window.clearTimeout(arm);
      window.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('keydown', onKeyDown, true);
    };
    // 함수들은 ref 만 읽으므로 선택이 생기고 사라질 때만 다시 건다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ctxValue.active]);

  // 선택이 없을 때도 Ctrl+V 로 이미지를 붙여 넣고, Ctrl+A 로 쪽의 이미지를 모두 고를 수 있게 한다.
  useEffect(() => {
    if (active || !ctxValue.active) return undefined;
    function onKeyDown(event) {
      if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) return;
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === 'v' && imageClipboard && lastCopyKind === 'image' && ctx.current.docRef.current.open) {
        event.preventDefault();
        event.stopImmediatePropagation();
        void pasteClip();
      }
    }
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ctxValue.active]);

  return {
    items,
    active,
    stamps,
    guides,
    eyedrop,
    setEyedrop,
    hasClipboard: () => Boolean(imageClipboard) && lastCopyKind === 'image',
    hasSelection: () => itemsRef.current.length > 0,
    place,
    selectStamp,
    commit,
    discard,
    reset,
    deleteSelected,
    beginGesture,
    moveGesture,
    resizeTo,
    endGesture,
    transformPrimary,
    alignSelected,
    patchSelected,
    pickBackground,
    copySelected,
    cutSelected,
    pasteClip,
    duplicateSelected,
    applyToPages,
    flatten,
    nudgeSelected,
    draggingRef,
  };
}
