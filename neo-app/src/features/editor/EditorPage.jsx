import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useDialog } from '../../context/DialogContext.jsx';
import { api, getWindowId } from '../../lib/apiClient.js';
import { useRegisterEditorCommands } from './editorCommands.jsx';
import PageSide, { PanelToggleTab } from './PageSide.jsx';
import { DocumentTabBar, ReduceSizeDialog, SearchDropdown } from './editorDialogs.jsx';
import PageNumberDialog from './PageNumberDialog.jsx';
import ExportImagesDialog from './ExportImagesDialog.jsx';
import HwpConvertDialog from './HwpConvertDialog.jsx';
import MergePdfDialog from './MergePdfDialog.jsx';
import PasswordOpenDialog from './PasswordOpenDialog.jsx';
import PasswordSetDialog from './PasswordSetDialog.jsx';
import PiiRemoveDialog from './PiiRemoveDialog.jsx';
import OcrDialog from './OcrDialog.jsx';
import TextMarkupLayer from './TextMarkupLayer.jsx';
import TerminalPanel from './TerminalPanel.jsx';

const EMPTY_DOC = { open: false, name: '', path: null, pageCount: 0, modified: false };
const MIN_ZOOM = 0.2;
const MAX_ZOOM = 5;
const ZOOM_STEP = 1.1;
const ZOOM_PRESETS = [25, 50, 75, 100, 125, 150, 200, 250, 300, 350, 400, 500];

const barBtnClass =
  'inline-flex h-[22px] w-6 shrink-0 items-center justify-center rounded border border-slate-300 bg-white text-[12px] text-slate-700 hover:bg-slate-50 disabled:opacity-40';
const fitBtnClass =
  'inline-flex h-[22px] w-9 shrink-0 items-center justify-center rounded border border-slate-300 bg-white text-[11px] font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40';

function NavIcon({ kind }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' };
  if (kind === 'first') {
    return (
      <svg viewBox="0 0 18 14" width="14" height="11" aria-hidden="true">
        <path d="M4 2v10" {...common} />
        <path d="M15 2 9 7l6 5" {...common} />
      </svg>
    );
  }
  if (kind === 'last') {
    return (
      <svg viewBox="0 0 18 14" width="14" height="11" aria-hidden="true">
        <path d="M14 2v10" {...common} />
        <path d="M3 2l6 5-6 5" {...common} />
      </svg>
    );
  }
  if (kind === 'prev') {
    return (
      <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
        <path d="M9 2 4 7l5 5" {...common} />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
      <path d="M5 2l5 5-5 5" {...common} />
    </svg>
  );
}

/** 개인정보 미리보기: 원본 show_review_rects 처럼 찾은 곳은 빨강, 같은 쪽의 다른 선택 항목은 옅게. */
function ReviewRectLayer({ focus, others }) {
  const box = (rect, key, tone) => {
    const [x0, y0, x1, y1] = rect;
    return (
      <div
        key={key}
        className={tone === 'focus' ? 'absolute border-2 border-red-500 bg-red-500/20' : 'absolute border border-red-400/80 bg-red-400/10'}
        style={{
          left: `${x0 * 100}%`,
          top: `${y0 * 100}%`,
          width: `${(x1 - x0) * 100}%`,
          height: `${(y1 - y0) * 100}%`,
        }}
      />
    );
  };
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
      {others.map((rect, index) => box(rect, `o-${index}`, 'other'))}
      {focus.map((rect, index) => box(rect, `f-${index}`, 'focus'))}
    </div>
  );
}

/** 개인정보 제거 결과 표기 (원본 format_pii_count 와 같은 형식). */
function countText(hitCount, areaCount) {
  return `${hitCount}건(영역 ${areaCount}개)`;
}

/** 원본 _run_ocr 의 결과 안내 문구 (건너뜀 / 인식 없음 / 완료 구분). */
function ocrResultMessage(result) {
  if (result.applied === 0 && result.skipped) {
    return '이미 텍스트가 있는 페이지는 건너뛰었습니다.\n스캔본만 다시 선택해 주세요.';
  }
  if (result.applied === 0) return '인식된 줄이 없습니다.';
  return `${result.applied}페이지 · ${result.lines}줄 인식\n건너뜀 ${result.skipped} · 실패 ${result.failed}`;
}

// 연속 스크롤에서 현재 쪽 위아래로 미리 그릴 행 수(한쪽씩 보기는 쪽 1개, 두쪽씩 보기는 쪽 2개가 한 행).
const WINDOW_BEFORE_ROWS = 2;
const WINDOW_AFTER_ROWS = 3;
// 쪽 크기를 모를 때 쓰는 기본값(A4, pt).
const FALLBACK_PAGE_PT = [595, 842];

/** 현재 쪽을 중심으로 그릴 쪽 번호 목록. 가까운 쪽부터 나온다. */
function windowIndices(center, facingMode, count) {
  const step = facingMode ? 2 : 1;
  const row = Math.floor(center / step);
  const from = Math.max(0, (row - WINDOW_BEFORE_ROWS) * step);
  const to = Math.min(count - 1, (row + WINDOW_AFTER_ROWS) * step + step - 1);
  const list = [];
  for (let i = from; i <= to; i += 1) list.push(i);
  return list.sort((a, b) => Math.abs(a - center) - Math.abs(b - center));
}

/** Neo editor: Tiny PDF Editor features via the headless engine. */
export default function EditorPage() {
  const dialog = useDialog();
  const [status, setStatus] = useState(/** @type {{ ready: boolean, error?: string } | null} */ (null));
  const [doc, setDoc] = useState(EMPTY_DOC);
  const [pageIndex, setPageIndex] = useState(0);
  const [zoom, setZoom] = useState(1.25);
  // 연속 스크롤: 쪽 그림은 배율(zoom)별로 보관한다. 화면에 필요한 근처 쪽만 그린다.
  const [pageSrcs, setPageSrcs] = useState(/** @type {{ zoom: number, map: Record<number, string> }} */ ({ zoom: 0, map: {} }));
  // 쪽별 크기(pt). 아직 그리지 않은 쪽도 제 높이로 자리를 잡아 스크롤이 튀지 않게 한다.
  const [pageSizes, setPageSizes] = useState(/** @type {number[][]} */ ([]));
  const [thumbs, setThumbs] = useState(/** @type {string[]} */ ([]));
  const [markups, setMarkups] = useState(/** @type {any[] | null} */ (null));
  const [markupTabRequest, setMarkupTabRequest] = useState(0);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  // 원본 하단 "터미널": 작업 시작 시 열리고, 엔진 진행 로그가 쌓인다.
  const [terminal, setTerminal] = useState({ open: false, expanded: true, lines: /** @type {string[]} */ ([]) });

  const startTerminal = useCallback((title) => {
    setTerminal({ open: true, expanded: true, lines: [`> ${title}`] });
  }, []);

  const appendTerminal = useCallback((line) => {
    setTerminal((prev) => ({ ...prev, lines: [...prev.lines, line] }));
  }, []);

  useEffect(() => {
    const subscribe = window.frame?.onPdfLog;
    if (typeof subscribe !== 'function') return undefined;
    const myWindowId = getWindowId();
    return subscribe((/** @type {{ message?: string, windowId?: string }} */ payload) => {
      // 다른 문서 창의 엔진 로그는 이 창의 터미널에 섞지 않는다.
      if (payload?.message && payload.windowId === myWindowId) appendTerminal(payload.message);
    });
  }, [appendTerminal]);

  // 새 문서 창: 메인 창이 넘긴 파일(?open=...)을 이 창의 엔진으로 연다.
  useEffect(() => {
    const url = new URL(window.location.href);
    const target = url.searchParams.get('open');
    if (!target) return;
    url.searchParams.delete('open');
    window.history.replaceState(null, '', url.toString());
    void openRecent(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [passwordPath, setPasswordPath] = useState('');
  const [passwordRejected, setPasswordRejected] = useState(false);
  const [facing, setFacing] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState(/** @type {any[]} */ ([]));
  // 마지막으로 Enter 로 실행한 검색어. 입력만 바뀌고 아직 Enter 를 안 누른 상태와 구분한다.
  const [searchRanQuery, setSearchRanQuery] = useState('');
  const [searchIndex, setSearchIndex] = useState(0);
  const [signatureOutside, setSignatureOutside] = useState(false);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  // undefined: 대화상자 닫힘 / null: 전체 페이지 / number[]: 선택한 페이지만
  const [piiScope, setPiiScope] = useState(/** @type {undefined | null | number[]} */ (undefined));
  // 개인정보 미리보기 빨간 상자 (0..1 비율). 현재 쪽에만 그린다.
  const [reviewRects, setReviewRects] = useState(
    /** @type {null | { pageIndex: number, focus: number[][], others: number[][] }} */ (null),
  );
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [reduceOpen, setReduceOpen] = useState(false);
  const [pageNumberOpen, setPageNumberOpen] = useState(false);
  // 이미지로 저장 옵션창 범위: null 이면 닫힘, { indices: null } 은 문서 전체, { indices: [..] } 은 선택 페이지.
  const [exportScope, setExportScope] = useState(null);
  // OCR 옵션창: null 이면 닫힘, { indices: null } 은 범위 입력 모드, { indices: [..] } 은 썸네일 선택 모드.
  const [ocrScope, setOcrScope] = useState(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [showFullscreenExit, setShowFullscreenExit] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [hwpOpen, setHwpOpen] = useState(false);
  const [clipboardCount, setClipboardCount] = useState(0);
  const requestId = useRef(0);
  const zoomRef = useRef(zoom);
  const viewRef = useRef(null);
  const imageRef = useRef(null);
  // 쪽 그림 맵 원본(렌더 함수 안에서 바로 읽을 수 있게 ref 로도 가진다).
  const pageMapRef = useRef({ zoom: 0, map: /** @type {Record<number, string>} */ ({}) });
  // 근처 쪽 그리기 작업 번호. 새 작업이 시작되면 이전 작업은 다음 쪽부터 멈춘다.
  const windowTokenRef = useRef(0);
  // 쪽 새로 그리기(편집 뒤 등)가 진행 중이면 스크롤 기반 보충 작업은 건너뛴다.
  const forceInFlightRef = useRef(false);
  const pageIndexRef = useRef(0);
  pageIndexRef.current = pageIndex;
  const docRef = useRef(doc);
  docRef.current = doc;
  const scrollRafRef = useRef(0);
  // 배율 바꿀 때 화면 중심이 같은 문서 위치에 남도록 저장하는 비율.
  const zoomAnchorRef = useRef(/** @type {number | null} */ (null));
  const searchInputRef = useRef(null);
  const searchQueryRef = useRef('');
  zoomRef.current = zoom;
  searchQueryRef.current = searchQuery;

  useEffect(() => {
    let cancelled = false;
    api('pdf.status')
      .then((data) => {
        if (cancelled) return;
        setStatus(data);
        // 원본 Tiny 처럼 실행하면 빈 문서 탭을 연다. 이미 열린 문서가 있거나 열 파일(?open=)이 있는 창은 건너뛴다.
        const hasOpenTarget = new URL(window.location.href).searchParams.has('open');
        if (data.ready && !data.doc?.open && !hasOpenTarget) {
          void newDoc();
        }
      })
      .catch((err) => {
        if (!cancelled) setStatus({ ready: false, error: err instanceof Error ? err.message : '상태를 확인하지 못했습니다.' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 연속 스크롤: 쪽 그림은 현재 쪽 근처만 그린다. 쪽 크기는 이미 알고 있으므로 자리는 미리 잡힌다.
  function commitPages(zoomValue, update) {
    const base = pageMapRef.current.zoom === zoomValue ? pageMapRef.current.map : {};
    const map = update(base);
    pageMapRef.current = { zoom: zoomValue, map };
    setPageSrcs({ zoom: zoomValue, map });
  }

  // 근처 쪽을 가까운 순서로 그린다. force 면 이미 있는 그림도 새로 그린다(편집 뒤 등).
  async function fetchWindow(center, nextZoom, token, facingMode, force) {
    const count = docRef.current.pageCount;
    if (!docRef.current.open || count < 1) return;
    const indices = windowIndices(center, facingMode, count);
    const keep = new Set(indices);
    // 창 밖의 그림은 버려서 메모리를 줄인다. 창 안의 그림은 새 그림이 올 때까지 남겨 깜빡이지 않게 한다.
    commitPages(nextZoom, (map) => {
      const next = {};
      for (const [key, src] of Object.entries(map)) {
        if (keep.has(Number(key))) next[Number(key)] = src;
      }
      return next;
    });
    for (const index of indices) {
      if (windowTokenRef.current !== token) return;
      const cached = pageMapRef.current.zoom === nextZoom ? pageMapRef.current.map[index] : undefined;
      if (cached && !force) continue;
      const image = await api('pdf.render', { index, zoom: nextZoom });
      if (windowTokenRef.current !== token) return;
      commitPages(nextZoom, (map) => ({ ...map, [index]: `data:image/png;base64,${image.png}` }));
    }
  }

  const loadPage = useCallback(async (index, nextZoom, token, facingMode = facing) => {
    setBusy('페이지를 그리는 중');
    const wtoken = ++windowTokenRef.current;
    forceInFlightRef.current = true;
    try {
      await fetchWindow(index, nextZoom, wtoken, facingMode, true);
    } finally {
      forceInFlightRef.current = false;
      if (requestId.current === token) setBusy('');
    }
  }, [facing]);

  // 쪽이 바뀌거나 배율·한쪽/두쪽 보기가 바뀌면 근처 쪽을 채운다. 이미 그린 쪽은 다시 그리지 않는다.
  useEffect(() => {
    if (!doc.open || doc.pageCount < 1) return;
    if (forceInFlightRef.current) return;
    const wtoken = ++windowTokenRef.current;
    fetchWindow(pageIndex, zoom, wtoken, facing, false).catch((err) => {
      setError(err instanceof Error ? err.message : '페이지를 그리지 못했습니다.');
    });
    // fetchWindow 는 ref 와 setter 만 써서 매 렌더마다 새로 만들어도 결과가 같다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageIndex, zoom, facing, doc.open, doc.pageCount]);

  // 화면 중심이 이 비율보다 위에 있는 쪽을 현재 쪽으로 본다(위쪽 1/3 기준선).
  function onViewerScroll() {
    if (scrollRafRef.current) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = 0;
      const view = viewRef.current;
      if (!view || !docRef.current.open) return;
      const anchor = view.getBoundingClientRect().top + view.clientHeight * 0.3;
      let found = 0;
      for (const el of view.querySelectorAll('[data-page]')) {
        if (el.getBoundingClientRect().top <= anchor) found = Number(el.dataset.page);
        else break;
      }
      const snapped = facing ? found - (found % 2) : found;
      if (snapped !== pageIndexRef.current) setPageIndex(snapped);
    });
  }

  function scrollToPage(index) {
    const view = viewRef.current;
    const el = view?.querySelector(`[data-page="${index}"]`);
    if (!view || !el) return;
    const top = el.getBoundingClientRect().top - view.getBoundingClientRect().top + view.scrollTop - 24;
    view.scrollTo({ top: Math.max(0, top), behavior: 'auto' });
  }

  const showDocument = useCallback(
    async (nextDoc, index = 0) => {
      const token = ++requestId.current;
      setDoc(nextDoc);
      setPageIndex(index);
      pageMapRef.current = { zoom: 0, map: {} };
      setPageSrcs({ zoom: 0, map: {} });
      setPageSizes([]);
      setThumbs(Array.from({ length: nextDoc.pageCount || 0 }, () => ''));
      setMarkups(nextDoc.open ? null : []);
      setError('');
      if (!nextDoc.open || nextDoc.pageCount < 1) {
        setBusy('');
        return;
      }
      void api('pdf.markups')
        .then((listed) => {
          if (requestId.current !== token) return;
          setMarkups(listed.entries ?? []);
        })
        .catch(() => {
          if (requestId.current === token) setMarkups([]);
        });
      void api('pdf.pageSizes')
        .then((listed) => {
          if (requestId.current === token) setPageSizes(listed.sizes ?? []);
        })
        .catch(() => {
          if (requestId.current === token) setPageSizes([]);
        });
      await loadPage(index, zoomRef.current, token);
      for (let i = 0; i < nextDoc.pageCount; i += 1) {
        if (requestId.current !== token) return;
        const image = await api('pdf.render', { index: i, thumb: true });
        if (requestId.current !== token) return;
        setThumbs((prev) => {
          const copy = prev.slice();
          copy[i] = `data:image/png;base64,${image.png}`;
          return copy;
        });
      }
    },
    [loadPage],
  );

  async function openPicked() {
    setError('');
    setPasswordPath('');
    setPasswordRejected(false);
    try {
      const picked = await api('pdf.pickPath');
      if (picked.canceled) return;
      await openFileTarget(picked.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : '파일을 열지 못했습니다.');
    }
  }

  // 비밀번호 확인 대화상자에서 입력한 암호로 연다. 틀리면 같은 대화상자에 안내를 남긴다.
  async function submitPassword(nextPassword) {
    if (!passwordPath || !nextPassword) return;
    setError('');
    try {
      const opened = await api('pdf.open', { path: passwordPath, password: nextPassword });
      if (opened.needsPassword) {
        setPasswordRejected(true);
        return;
      }
      setPasswordPath('');
      setPasswordRejected(false);
      await showDocument(opened.doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : '파일을 열지 못했습니다.');
    }
  }

  function cancelPassword() {
    setPasswordPath('');
    setPasswordRejected(false);
  }

  // 쪽으로 이동: 쪽 그림을 바꾸는 대신 그 쪽의 자리로 스크롤한다. 근처 쪽 그리기는 effect 가 맡는다.
  function goTo(index) {
    if (!doc.open || index < 0 || index >= doc.pageCount) return;
    const target = facing ? index - (index % 2) : index;
    setError('');
    setPageIndex(target);
    scrollToPage(target);
  }

  // 배율만 바꾼다. 그림은 effect 가 새 배율로 다시 그리고, 화면 중심은 같은 문서 위치에 남긴다.
  function changeZoom(next) {
    const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(next * 100) / 100));
    if (clamped === zoomRef.current) return;
    const view = viewRef.current;
    if (doc.open && view) {
      zoomAnchorRef.current = (view.scrollTop + view.clientHeight / 2) / Math.max(1, view.scrollHeight);
    }
    // 휠을 연속으로 굴릴 때 같은 렌더 사이클 안에서도 최신 배율을 쓰도록 바로 갱신한다.
    zoomRef.current = clamped;
    setZoom(clamped);
  }

  // 배율이 바뀌어 자리가 다시 잡힌 뒤 화면 중심을 복원한다.
  useLayoutEffect(() => {
    const anchor = zoomAnchorRef.current;
    const view = viewRef.current;
    zoomAnchorRef.current = null;
    if (anchor == null || !view) return;
    view.scrollTop = anchor * view.scrollHeight - view.clientHeight / 2;
  }, [zoom]);

  function commitPageInput(raw) {
    const value = Number.parseInt(String(raw).replace(/[^\d]/g, ''), 10);
    if (!Number.isFinite(value)) return;
    void goTo(value - 1);
  }

  function applyZoomPercent(raw) {
    const cleaned = String(raw).replace('%', '').trim();
    const value = Number.parseFloat(cleaned);
    if (!Number.isFinite(value)) return;
    void changeZoom(value / 100);
  }

  async function save() {
    setError('');
    try {
      const saved = doc.path ? await api('pdf.save') : await api('pdf.pickSave');
      if (saved.canceled) return;
      setDoc(saved.doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장하지 못했습니다.');
    }
  }

  async function saveAs() {
    setError('');
    try {
      const saved = await api('pdf.pickSave');
      if (saved.canceled) return;
      setDoc(saved.doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장하지 못했습니다.');
    }
  }

  async function closeDoc() {
    const token = ++requestId.current;
    setError('');
    try {
      const closed = await api('pdf.close');
      if (requestId.current !== token) return;
      // 원본 Tiny: 마지막 탭을 닫으면 빈 문서 탭을 바로 다시 만든다.
      const created = await api('pdf.new');
      if (requestId.current !== token) return;
      await showDocument(created.doc ?? closed.doc ?? EMPTY_DOC);
      setPasswordPath('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '문서를 닫지 못했습니다.');
    }
  }

  async function applyDocResult(result, preferredIndex = pageIndex) {
    if (!result?.doc?.open) {
      await showDocument(EMPTY_DOC);
      return;
    }
    const nextIndex = Math.max(0, Math.min(preferredIndex, (result.doc.pageCount || 1) - 1));
    await showDocument(result.doc, nextIndex);
  }

  // 형광펜·밑줄 추가/삭제 뒤: 뷰어 스크롤과 쪽 위치는 그대로 두고 쪽 그림, 썸네일, 목록만 다시 만든다.
  async function refreshAfterMarkup(nextDoc) {
    const token = ++requestId.current;
    const hadMarkups = (markups?.length ?? 0) > 0;
    setDoc(nextDoc);
    void api('pdf.markups')
      .then((listed) => {
        if (requestId.current !== token) return;
        const entries = listed.entries ?? [];
        setMarkups(entries);
        if (!hadMarkups && entries.length > 0) setMarkupTabRequest((value) => value + 1);
      })
      .catch(() => {});
    await loadPage(pageIndex, zoomRef.current, token);
    try {
      const thumb = await api('pdf.render', { index: pageIndex, thumb: true });
      if (requestId.current !== token) return;
      setThumbs((prev) => {
        const copy = prev.slice();
        copy[pageIndex] = `data:image/png;base64,${thumb.png}`;
        return copy;
      });
    } catch {
      // 썸네일 갱신 실패는 본문 표시에 영향이 없으니 무시한다.
    }
  }

  function notifyMarkup(body) {
    void dialog.alert({ title: '형광펜 · 밑줄', body });
  }

  async function newDoc() {
    setError('');
    try {
      const created = await api('pdf.new');
      await showDocument(created.doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : '새 문서를 만들지 못했습니다.');
    }
  }

  async function insertFiles() {
    setError('');
    try {
      const result = await api('pdf.insert', { index: pageIndex + 1 });
      if (result.canceled) return;
      await applyDocResult(result, pageIndex);
    } catch (err) {
      setError(err instanceof Error ? err.message : '파일을 추가하지 못했습니다.');
    }
  }

  // 원본 PDF 병합: 대화상자에서 파일을 모아 저장한 뒤, 저장된 파일을 연다.
  function mergeFiles() {
    setError('');
    setMergeOpen(true);
  }

  /**
   * 원본 _open_paths: 문서가 열려 있고 '새 창으로 열기'이면 새 창에서 연다.
   * 그 밖에는 이 창에서 연다. 브라우저(창 기능 없음)는 항상 이 창에서 연다.
   */
  async function openFileTarget(filePath) {
    const native = window.frame;
    if (doc.open && native?.openDocumentWindow) {
      try {
        const { openInNewWindow } = await api('pdf.openTargetGet');
        if (openInNewWindow) {
          await native.openDocumentWindow(filePath);
          return;
        }
      } catch {
        // 설정을 읽지 못하면 이 창에서 연다.
      }
    }
    await openRecent(filePath);
  }

  async function openRecent(filePath) {
    setError('');
    try {
      const opened = await api('pdf.open', { path: filePath });
      if (opened.needsPassword) {
        setPasswordPath(filePath);
        setPasswordRejected(Boolean(opened.rejected));
        return;
      }
      await showDocument(opened.doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : '최근 파일을 열지 못했습니다.');
    }
  }

  async function refreshClipboardCount() {
    try {
      const clip = await api('pdf.pageClipboard');
      setClipboardCount(Number(clip.count) || 0);
    } catch {
      setClipboardCount(0);
    }
  }

  async function deletePages(indices) {
    const list = (indices || []).filter((index) => Number.isInteger(index));
    if (!doc.open || !list.length) {
      void dialog.alert({ title: '삭제', body: '삭제할 페이지를 선택하세요.' });
      return;
    }
    const ok = await dialog.confirm({
      title: '페이지 삭제',
      body: `${list.length}개 페이지를 삭제하시겠습니까?`,
      confirmVariant: 'danger',
    });
    if (!ok) return;
    setError('');
    try {
      const result = await api('pdf.deletePages', { indices: list });
      await applyDocResult(result, Math.max(0, Math.min(...list) - 1));
    } catch (err) {
      setError(err instanceof Error ? err.message : '페이지를 삭제하지 못했습니다.');
    }
  }

  async function deleteCurrentPage() {
    await deletePages([pageIndex]);
  }

  async function handleThumbAction(action) {
    const indices = Array.isArray(action.indices) ? action.indices.map(Number) : [];
    const targetIndex = Number.isInteger(action.targetIndex) ? action.targetIndex : pageIndex + 1;
    setError('');
    try {
      switch (action.type) {
        case 'delete':
          await deletePages(indices);
          return;
        case 'rotate': {
          if (!indices.length) return;
          const result = await api('pdf.rotatePages', { indices, degrees: action.degrees || 90 });
          await applyDocResult(result, pageIndex);
          return;
        }
        case 'movePages': {
          if (!indices.length) return;
          const result = await api('pdf.movePages', { indices, targetIndex });
          if (result.insertAt == null) return;
          await applyDocResult(result, result.insertAt);
          return;
        }
        case 'insertBlank': {
          const result = await api('pdf.insertBlank', { index: targetIndex });
          await applyDocResult(result, result.index ?? targetIndex);
          return;
        }
        case 'insertFiles': {
          const result = await api('pdf.insert', {
            index: targetIndex,
            paths: Array.isArray(action.paths) ? action.paths : undefined,
          });
          if (result.canceled) return;
          await applyDocResult(result, targetIndex);
          return;
        }
        case 'copy': {
          if (!indices.length) return;
          const result = await api('pdf.copyPages', { indices });
          setClipboardCount(result.count || indices.length);
          return;
        }
        case 'cut': {
          if (!indices.length) return;
          const result = await api('pdf.cutPages', { indices });
          setClipboardCount(result.count || indices.length);
          await applyDocResult(result, Math.max(0, Math.min(...indices) - 1));
          return;
        }
        case 'paste': {
          const result = await api('pdf.pastePages', { index: targetIndex });
          await applyDocResult(result, targetIndex);
          await refreshClipboardCount();
          return;
        }
        case 'exportImages': {
          if (!indices.length) return;
          setExportScope({ indices });
          return;
        }
        case 'exportPdf': {
          if (!indices.length) return;
          const result = await api('pdf.exportPagesPdf', { indices });
          if (result.canceled) return;
          void dialog.alert({ title: '새 파일로 저장', body: `저장됨: ${result.path}` });
          return;
        }
        case 'undo':
          await undoRedo('undo');
          return;
        case 'redo':
          await undoRedo('redo');
          return;
        case 'ocr':
          setOcrScope(Array.isArray(indices) ? { indices } : { indices: null });
          return;
        case 'pii':
          await removePii(indices);
          return;
        case 'piiAll':
          await removePii(null);
          return;
        case 'print': {
          if (!indices.length) return;
          await api('pdf.print', { indices });
          return;
        }
        case 'printAll':
          await printDoc();
          return;
        default:
          break;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '썸네일 작업을 하지 못했습니다.');
    }
  }

  async function rotateAll(degrees) {
    setError('');
    try {
      const result = await api('pdf.rotatePages', { degrees, indices: [] });
      await applyDocResult(result, pageIndex);
    } catch (err) {
      setError(err instanceof Error ? err.message : '회전하지 못했습니다.');
    }
  }

  async function undoRedo(kind) {
    setError('');
    try {
      const result = await api(kind === 'undo' ? 'pdf.undo' : 'pdf.redo');
      if (!result.changed) {
        void dialog.alert({ title: kind === 'undo' ? '되돌리기' : '재실행', body: '더 이상 할 수 없습니다.' });
        return;
      }
      await applyDocResult(result, pageIndex);
    } catch (err) {
      setError(err instanceof Error ? err.message : '실행하지 못했습니다.');
    }
  }

  /** 옵션창에서 "폴더 선택..." 을 누른 뒤 실행. scope.indices 가 있으면 썸네일 선택 페이지만 저장. */
  async function runExportImages(scope, options) {
    setExportScope(null);
    setError('');
    setBusy('이미지로 저장 중');
    try {
      if (scope?.indices) {
        const result = await api('pdf.exportPagesImages', { indices: scope.indices, options });
        if (result.canceled) return;
        void dialog.alert({ title: '이미지로 저장', body: `${result.count}개 이미지를 저장했습니다.\n${result.dir}` });
      } else {
        // 완료 후 폴더 열기 질문은 Electron 쪽 대화상자에서 처리한다.
        await api('pdf.exportImages', { options });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '이미지로 저장하지 못했습니다.');
    } finally {
      setBusy('');
    }
  }

  async function runSearch(query = searchQuery) {
    const text = String(query || '').trim();
    setSearchOpen(true);
    if (!text) {
      setSearchHits([]);
      setSearchIndex(0);
      setSearchRanQuery('');
      return;
    }
    setError('');
    try {
      const result = await api('pdf.search', { query: text });
      const hits = result.hits ?? [];
      setSearchHits(hits);
      setSearchIndex(0);
      setSearchRanQuery(text);
      if (hits.length) await goTo(hits[0].pageIndex);
    } catch (err) {
      setError(err instanceof Error ? err.message : '검색하지 못했습니다.');
    }
  }

  function closeSearch() {
    setSearchOpen(false);
    setSearchHits([]);
    setSearchIndex(0);
    setSearchRanQuery('');
  }

  async function jumpSearch(delta) {
    if (!searchHits.length) {
      await runSearch(searchQueryRef.current);
      return;
    }
    const next = (searchIndex + delta + searchHits.length) % searchHits.length;
    setSearchIndex(next);
    await goTo(searchHits[next].pageIndex);
  }

  async function submitSearch() {
    const text = searchQueryRef.current.trim();
    if (!text) return;
    if (searchHits.length && searchQuery.trim() === text) {
      await jumpSearch(1);
      return;
    }
    await runSearch(text);
  }

  async function copyCutPaste(kind) {
    setError('');
    try {
      if (kind === 'paste') {
        const result = await api('pdf.pastePages', { index: pageIndex + 1 });
        await applyDocResult(result, pageIndex);
        await refreshClipboardCount();
        return;
      }
      const indices = [pageIndex];
      if (kind === 'copy') {
        const result = await api('pdf.copyPages', { indices });
        setClipboardCount(result.count || indices.length);
        void dialog.alert({ title: '복사', body: `${result.count}페이지를 복사했습니다.` });
        return;
      }
      const result = await api('pdf.cutPages', { indices });
      setClipboardCount(result.count || indices.length);
      await applyDocResult(result, Math.max(0, pageIndex - 1));
    } catch (err) {
      setError(err instanceof Error ? err.message : '클립보드 작업을 하지 못했습니다.');
    }
  }

  async function applyReduceSize(options) {
    setReduceOpen(false);
    setError('');
    startTerminal('용량 줄이기 작업을 시작합니다...');
    try {
      setBusy('용량을 줄이는 중');
      const result = await api('pdf.reduceSize', options);
      setBusy('');
      await applyDocResult(result, pageIndex);
      const beforeKb = Math.round((result.before || 0) / 1024);
      const afterKb = Math.round((result.after || 0) / 1024);
      appendTerminal(`완료: ${beforeKb}KB → ${afterKb}KB`);
      void dialog.alert({ title: '용량 줄이기', body: `${beforeKb}KB → ${afterKb}KB` });
    } catch (err) {
      setBusy('');
      const message = err instanceof Error ? err.message : '용량을 줄이지 못했습니다.';
      appendTerminal(`오류: ${message}`);
      setError(message);
    }
  }

  async function applyPageNumbers(options) {
    setPageNumberOpen(false);
    setError('');
    try {
      const result = await api('pdf.pageNumbers', { options });
      await applyDocResult(result, pageIndex);
    } catch (err) {
      setError(err instanceof Error ? err.message : '쪽 번호를 넣지 못했습니다.');
    }
  }

  async function handleOcrApply(payload, scope) {
    setOcrScope(null);
    let mode, indices;
    if (payload.scope === 'current') {
      mode = 'current';
      indices = null;
    } else if (payload.scope === 'selected') {
      mode = 'selected';
      indices = scope?.indices; // 썸네일 선택 페이지
    } else if (payload.scope === 'all') {
      mode = 'all';
      indices = null;
    } else if (payload.scope === 'range') {
      // 범위 선택: 페이지 인덱스로 변환
      mode = 'selected';
      indices = Array.from({ length: payload.pageTo - payload.pageFrom + 1 }, (_, i) => payload.pageFrom - 1 + i);
    }
    await runOcr(mode, indices);
  }

  async function runOcr(mode, indices) {
    setError('');
    startTerminal('OCR을 시작합니다...');
    try {
      const targets = mode === 'all' ? doc.pageCount : mode === 'selected' ? (indices?.length ? indices.length : 1) : 1;
      setBusy(`OCR 중 · ${targets}페이지 인식 (시간이 걸릴 수 있습니다)`);
      const body =
        mode === 'all'
          ? { mode: 'all' }
          : mode === 'selected'
            ? { indices: indices?.length ? indices : [pageIndex] }
            : { mode: 'current', index: pageIndex };
      const result = await api('pdf.ocr', body);
      setBusy('');
      await applyDocResult(result, pageIndex);
      appendTerminal(
        `완료: ${result.applied}페이지, ${result.lines}줄 (건너뜀 ${result.skipped}, 실패 ${result.failed})`,
      );
      void dialog.alert({ title: 'OCR', body: ocrResultMessage(result) });
    } catch (err) {
      setBusy('');
      const message = err instanceof Error ? err.message : 'OCR을 하지 못했습니다.';
      appendTerminal(`오류: ${message}`);
      setError(message);
    }
  }

  /** 비밀번호 설정: 원본 SetPasswordDialog 처럼 별도 대화상자를 연다. */
  function setDocPassword() {
    if (!doc.open || doc.pageCount < 1) {
      void dialog.alert({ title: 'PDF 비밀번호', body: '페이지가 있는 문서를 열어주세요.' });
      return;
    }
    setError('');
    setPasswordDialogOpen(true);
  }

  function onPasswordApplied(nextDoc) {
    setDoc(nextDoc);
    void dialog.alert({
      title: '비밀번호 설정',
      body: '비밀번호가 설정되었습니다. 저장하면 암호가 적용된 PDF로 저장됩니다.',
    });
  }

  /** 비밀번호 제거: 원본과 같이 확인 후 제거. 설정된 암호가 없으면 아무것도 하지 않는다. */
  async function clearPassword() {
    if (!doc.open || !doc.passwordProtected) return;
    const ok = await dialog.confirm({
      title: 'PDF 비밀번호',
      body: '비밀번호를 제거하시겠습니까?\n저장하면 암호 없는 PDF로 저장됩니다.',
    });
    if (!ok) return;
    setError('');
    try {
      const result = await api('pdf.clearPassword');
      setDoc(result.doc);
      void dialog.alert({
        title: 'PDF 비밀번호',
        body: '비밀번호가 제거되었습니다. 저장하면 암호 없는 PDF로 저장됩니다.',
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '비밀번호를 제거하지 못했습니다.');
    }
  }

  /** 개인정보 제거: 원본 PiiRemoveDialog 처럼 검사 → 목록 선택 → 제거 흐름을 대화상자로 연다. */
  function removePii(pageIndices = null) {
    if (!doc.open || doc.pageCount < 1) {
      void dialog.alert({ title: '개인정보 제거', body: '페이지가 있는 문서를 열어주세요.' });
      return;
    }
    setError('');
    setPiiScope(Array.isArray(pageIndices) ? pageIndices : null);
  }

  function closePiiDialog() {
    setPiiScope(undefined);
    setReviewRects(null);
  }

  /** 목록 행을 누르면 해당 페이지로 이동하고 빨간 상자로 범위를 보여준다. */
  function previewPiiHit(hit, selected) {
    const samepage = selected.filter((other) => other !== hit && other.pageIndex === hit.pageIndex);
    setReviewRects({
      pageIndex: hit.pageIndex,
      focus: hit.previewRects ?? [],
      others: samepage.flatMap((other) => other.previewRects ?? []),
    });
    if (hit.pageIndex !== pageIndex) void goTo(hit.pageIndex);
  }

  async function applyPiiRedact(hits, style) {
    closePiiDialog();
    setError('');
    try {
      startTerminal('개인정보 제거를 시작합니다...');
      setBusy('개인정보 제거 중');
      const result = await api('pdf.piiRedact', { hits, style });
      setBusy('');
      await applyDocResult(result, pageIndex);
      const summary = countText(result.hitCount, result.areaCount);
      appendTerminal(`완료: ${summary}를 제거했습니다.`);
      void dialog.alert({
        title: '개인정보 제거',
        body: `${summary}의 원본 내용을 제거했습니다.\n저장 전에 결과를 확인하세요.`,
      });
    } catch (err) {
      setBusy('');
      const message = err instanceof Error ? err.message : '개인정보를 제거하지 못했습니다.';
      appendTerminal(`오류: ${message}`);
      setError(message);
    }
  }

  async function stampSignature(fromClipboard) {
    setError('');
    try {
      const result = await api('pdf.stampImage', {
        pageIndex,
        fromClipboard: Boolean(fromClipboard),
        pickFile: !fromClipboard,
      });
      if (result.canceled) return;
      await applyDocResult(result, pageIndex);
      if (signatureOutside) {
        void dialog.alert({ title: '서명 넣기', body: '서명을 넣었습니다. (바깥 클릭 확정 설정 켜짐)' });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '서명을 넣지 못했습니다.');
    }
  }

  // 원본 한글 → PDF: 대화상자에서 여러 파일을 모아 변환하고, 원하면 결과를 연다.
  function hwpConvert() {
    setError('');
    setHwpOpen(true);
  }

  async function printDoc() {
    setError('');
    try {
      await api('pdf.print');
    } catch (err) {
      setError(err instanceof Error ? err.message : '인쇄하지 못했습니다.');
    }
  }

  async function manageAssoc() {
    try {
      const statusInfo = await api('pdf.assocStatus');
      if (!statusInfo.windows) {
        void dialog.alert({ title: 'PDF 파일 연결', body: 'Windows에서만 사용할 수 있습니다.' });
        return;
      }
      const choice = await dialog.choose({
        title: 'PDF 파일 연결',
        body: statusInfo.registered ? '현재 연결되어 있습니다.' : '연결되어 있지 않습니다.',
        primaryLabel: statusInfo.registered ? '연결 해제' : '연결',
        extraLabel: '기본 앱 설정 열기',
        cancelLabel: '닫기',
      });
      if (choice === 'primary') {
        if (statusInfo.registered) await api('pdf.assocUnregister');
        else await api('pdf.assocRegister', { openSettings: true });
      } else if (choice === 'extra') {
        await api('pdf.assocRegister', { openSettings: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '파일 연결을 처리하지 못했습니다.');
    }
  }

  async function managePrinter() {
    try {
      const statusInfo = await api('pdf.printerStatus');
      if (!statusInfo.supported) {
        void dialog.alert({ title: '가상 프린터', body: '이 환경에서는 가상 프린터를 쓸 수 없습니다.' });
        return;
      }
      const choice = await dialog.choose({
        title: '가상 프린터',
        body: statusInfo.installed ? '설치되어 있습니다.' : '설치되어 있지 않습니다.',
        primaryLabel: statusInfo.installed ? '제거' : '설치',
        cancelLabel: '닫기',
      });
      if (choice !== 'primary') return;
      if (statusInfo.installed) await api('pdf.printerUninstall');
      else await api('pdf.printerInstall');
      void dialog.alert({
        title: '가상 프린터',
        body: statusInfo.installed ? '제거했습니다.' : '설치했습니다. 인쇄 스풀 감시는 기존처럼 유지됩니다.',
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '가상 프린터를 처리하지 못했습니다.');
    }
  }

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (event.key === 'F11') {
        event.preventDefault();
        setFullscreen((v) => !v);
        return;
      }
      if (event.key === 'Escape' && fullscreen) {
        setFullscreen(false);
        return;
      }
      if (event.key === 'ArrowLeft') void goTo(pageIndex - (facing ? 2 : 1));
      if (event.key === 'ArrowRight') void goTo(pageIndex + (facing ? 2 : 1));
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [fullscreen, facing, pageIndex]);

  // 연속 스크롤: 휠은 브라우저 기본 스크롤에 맡긴다. 쪽 끝에서 다음 쪽 위로 자연스럽게 이어진다.
  // (예전의 "끝에서 굴리면 쪽 맨 위로 점프" 방식은 제거했다.)

  // Ctrl+휠: 본문 배율 조절 (브라우저 기본 확대/축소는 막는다).
  // React onWheel 은 passive 라 preventDefault 가 안 먹으므로 네이티브 리스너를 직접 건다.
  const changeZoomRef = useRef(null);
  changeZoomRef.current = changeZoom;
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return undefined;
    function onCtrlWheelZoom(event) {
      if (!event.ctrlKey || !event.deltaY) return;
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
      void changeZoomRef.current?.(zoomRef.current * factor);
    }
    view.addEventListener('wheel', onCtrlWheelZoom, { passive: false });
    return () => view.removeEventListener('wheel', onCtrlWheelZoom);
  }, []);

  // 전체화면 모드: 마우스 상단 60px 감지 타이머
  useEffect(() => {
    if (!fullscreen) return undefined;
    const checkMousePos = () => {
      const y = window.pageYOffset;
      setShowFullscreenExit(y < 60);
    };
    const id = setInterval(checkMousePos, 120);
    return () => clearInterval(id);
  }, [fullscreen]);

  function fit(mode) {
    const view = viewRef.current;
    const image = imageRef.current;
    if (!view || !image?.naturalWidth) return;
    const pad = 48;
    const availW = Math.max(80, view.clientWidth - pad) / (facing ? 2 : 1);
    const availH = Math.max(80, view.clientHeight - pad);
    const pageW = image.naturalWidth / zoomRef.current;
    const pageH = image.naturalHeight / zoomRef.current;
    if (mode === 'width') void changeZoom(availW / pageW);
    else if (mode === 'height') void changeZoom(availH / pageH);
    else void changeZoom(Math.min(availW / pageW, availH / pageH));
  }

  const engineReady = status?.ready === true;
  useRegisterEditorCommands(
    {
      open: () => void openPicked(),
      openRecent: (filePath) => void openFileTarget(filePath),
      new: () => void newDoc(),
      add: () => void insertFiles(),
      merge: () => void mergeFiles(),
      save: () => void save(),
      saveAs: () => void saveAs(),
      close: () => void closeDoc(),
      exportImages: () => setExportScope({ indices: null }),
      print: () => void printDoc(),
      assoc: () => void manageAssoc(),
      printer: () => void managePrinter(),
      hwp: () => void hwpConvert(),
      undo: () => void undoRedo('undo'),
      redo: () => void undoRedo('redo'),
      copy: () => void copyCutPaste('copy'),
      cut: () => void copyCutPaste('cut'),
      paste: () => void copyCutPaste('paste'),
      find: () => {
        setSearchOpen(true);
        requestAnimationFrame(() => {
          searchInputRef.current?.focus();
          searchInputRef.current?.select();
        });
      },
      delete: () => void deleteCurrentPage(),
      rotateCw: () => void rotateAll(90),
      rotateCcw: () => void rotateAll(-90),
      reduce: () => setReduceOpen(true),
      pageNumber: () => setPageNumberOpen(true),
      ocr: () => setOcrScope({ indices: null }),
      sigClip: () => void stampSignature(true),
      sigFile: () => void stampSignature(false),
      sigOutside: () => setSignatureOutside((value) => !value),
      setPw: () => void setDocPassword(),
      clearPw: () => void clearPassword(),
      pii: () => void removePii(),
      fitWidth: () => fit('width'),
      fitHeight: () => fit('height'),
      fitPage: () => fit('page'),
      facing: () => {
        setFacing((value) => {
          const next = !value;
          const token = ++requestId.current;
          void loadPage(pageIndex, zoomRef.current, token, next);
          return next;
        });
      },
      getSignatureOutside: () => signatureOutside,
      getFacing: () => facing,
    },
    { ready: engineReady, docOpen: doc.open },
  );

  const zoomPercent = Math.round(zoom * 100);
  const canNav = doc.open && doc.pageCount > 0;
  // 한쪽씩 보기는 행마다 쪽 1개, 두쪽씩 보기는 쪽 2개.
  const pageRows = [];
  if (canNav) {
    const step = facing ? 2 : 1;
    for (let start = 0; start < doc.pageCount; start += step) {
      pageRows.push(Array.from({ length: Math.min(step, doc.pageCount - start) }, (_, k) => start + k));
    }
  }
  const statusHint = busy
    ? busy
    : doc.open
      ? `${doc.name}${doc.modified ? ' · 수정됨' : ''}`
      : '';

  return (
    <div className={`flex h-full min-h-0 flex-col ${fullscreen ? 'bg-black' : 'bg-app-surface'}`}>
      {!fullscreen && (
        <>
          {status && !engineReady ? (
            <p className="border-b border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
              {status.error || 'PDF 엔진을 시작하지 못했습니다.'}
            </p>
          ) : null}
          {error ? <p className="border-b border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}

          <DocumentTabBar
            docOpen={doc.open}
            docName={doc.path ? doc.name : '빈 문서(noname)'}
            modified={doc.modified}
            onClose={() => void closeDoc()}
          >
          </DocumentTabBar>
        </>
      )}

      <div className="flex min-h-0 flex-1">
        {!fullscreen && <PageSide
          docOpen={doc.open}
          pageIndex={pageIndex}
          pageCount={doc.pageCount || 0}
          thumbs={thumbs}
          markups={markups}
          markupTabRequest={markupTabRequest}
          clipboardCount={clipboardCount}
          onSelectPage={(index) => void goTo(index)}
          onThumbAction={(action) => void handleThumbAction(action)}
          collapsed={panelCollapsed}
          onCollapsedChange={setPanelCollapsed}
        />
        }

        <div className="relative flex min-w-0 flex-1 flex-col">
          {!fullscreen && (
            <PanelToggleTab
              collapsed={panelCollapsed}
              onToggle={() => setPanelCollapsed((value) => !value)}
            />
          )}
          {!fullscreen && searchOpen && doc.open ? (
            <SearchDropdown
              query={searchQuery}
              ranQuery={searchRanQuery}
              hits={searchHits}
              index={searchIndex}
              inputRef={searchInputRef}
              onQueryChange={(value) => {
                setSearchQuery(value);
                // 검색어가 바뀌면 이전 결과는 버리고, Enter 를 눌러야 새로 검색한다.
                setSearchHits([]);
                setSearchIndex(0);
                setSearchRanQuery('');
              }}
              onSubmit={() => void submitSearch()}
              onPrev={() => void jumpSearch(-1)}
              onNext={() => void jumpSearch(1)}
              onClose={closeSearch}
            />
          ) : null}
          <main ref={viewRef} className="min-h-0 flex-1 overflow-auto" onScroll={onViewerScroll}>
            {doc.open && doc.pageCount > 0 ? (
              // 연속 스크롤: 모든 쪽을 세로로 이어 놓는다. 쪽 크기를 알면 그리지 않은 쪽도 제 자리에 있다.
              <div className="flex min-h-full flex-col items-center justify-center gap-4 p-6">
                {pageRows.map((row) => (
                  <div key={row[0]} className="flex items-start justify-center gap-4">
                    {row.map((index) => {
                      const [ptW, ptH] = pageSizes[index] ?? FALLBACK_PAGE_PT;
                      const src = pageSrcs.zoom === zoom ? pageSrcs.map[index] : '';
                      const current = index === pageIndex;
                      return (
                        <div
                          key={index}
                          data-page={index}
                          className="relative max-w-full bg-white shadow-sm"
                          style={{ width: `${ptW * zoom}px`, aspectRatio: `${ptW} / ${ptH}` }}
                        >
                          {src ? (
                            <img
                              ref={current ? imageRef : undefined}
                              src={src}
                              alt={`${index + 1}쪽`}
                              className="block h-full w-full"
                            />
                          ) : null}
                          {current && src ? (
                            <TextMarkupLayer
                              pageIndex={pageIndex}
                              enabled={doc.open && !busy}
                              onMarkupChanged={(nextDoc) => void refreshAfterMarkup(nextDoc)}
                              onNotice={notifyMarkup}
                            />
                          ) : null}
                          {current && src && reviewRects && reviewRects.pageIndex === index ? (
                            <ReviewRectLayer focus={reviewRects.focus} others={reviewRects.others} />
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center p-8">
                <div className="max-w-md text-center">
                  <h1 className="m-0 text-lg font-semibold text-slate-800">PDF 편집 초안</h1>
                  <p className="mt-2 text-sm leading-relaxed text-slate-500">
                    파일 메뉴의 열기로 문서를 불러옵니다. 문서를 읽고 쪽 그림을 만드는 일은 이 PC의 Tiny PDF Editor 엔진이 합니다.
                  </p>
                  {busy ? <p className="mt-3 text-sm text-slate-500">{busy}</p> : null}
                </div>
              </div>
            )}
          </main>

          <TerminalPanel
            open={terminal.open}
            expanded={terminal.expanded}
            lines={terminal.lines}
            onToggleExpanded={() => setTerminal((prev) => ({ ...prev, expanded: !prev.expanded }))}
            onClose={() => setTerminal((prev) => ({ ...prev, open: false }))}
          />

          <footer className="flex h-9 shrink-0 items-center gap-1.5 border-t border-app-border bg-[#f7f7f7] px-2">
            <span className="mr-1 min-w-0 max-w-[28%] truncate text-[11px] text-slate-500" title={statusHint}>
              {statusHint}
            </span>
            <div className="mx-auto flex items-center gap-1">
              <button
                type="button"
                className={barBtnClass}
                title="맨 앞 페이지"
                disabled={!canNav || pageIndex <= 0}
                onClick={() => void goTo(0)}
              >
                <NavIcon kind="first" />
              </button>
              <button
                type="button"
                className={barBtnClass}
                title="이전 페이지"
                disabled={!canNav || pageIndex <= 0}
                onClick={() => void goTo(pageIndex - 1)}
              >
                <NavIcon kind="prev" />
              </button>
              <input
                type="text"
                inputMode="numeric"
                aria-label="페이지"
                disabled={!canNav}
                defaultValue={doc.open ? String(pageIndex + 1) : '1'}
                key={`page-${doc.open ? pageIndex : 'x'}-${doc.pageCount}`}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.currentTarget.blur();
                    commitPageInput(event.currentTarget.value);
                  }
                }}
                onBlur={(event) => commitPageInput(event.currentTarget.value)}
                className="h-[22px] w-16 rounded border border-slate-300 bg-white px-1 text-center text-[12px] text-slate-700 outline-none focus:border-app-accent disabled:opacity-50"
              />
              <span className="px-0.5 text-[12px] text-slate-600">/ {doc.open ? doc.pageCount : 0}</span>
              <button
                type="button"
                className={barBtnClass}
                title="다음 페이지"
                disabled={!canNav || pageIndex >= doc.pageCount - 1}
                onClick={() => void goTo(pageIndex + 1)}
              >
                <NavIcon kind="next" />
              </button>
              <button
                type="button"
                className={barBtnClass}
                title="마지막 페이지"
                disabled={!canNav || pageIndex >= doc.pageCount - 1}
                onClick={() => void goTo(doc.pageCount - 1)}
              >
                <NavIcon kind="last" />
              </button>

              <span className="mx-1 h-4 w-px bg-slate-300" />

              <button type="button" className={fitBtnClass} title="너비 맞추기" disabled={!doc.open} onClick={() => fit('width')}>
                너비
              </button>
              <button type="button" className={fitBtnClass} title="높이 맞추기" disabled={!doc.open} onClick={() => fit('height')}>
                높이
              </button>
              <button type="button" className={fitBtnClass} title="화면 맞추기" disabled={!doc.open} onClick={() => fit('page')}>
                화면
              </button>

              <button
                type="button"
                className={barBtnClass}
                title="축소"
                disabled={!doc.open || zoom <= MIN_ZOOM}
                onClick={() => void changeZoom(zoom / ZOOM_STEP)}
              >
                −
              </button>
              <input
                type="range"
                min={MIN_ZOOM * 100}
                max={MAX_ZOOM * 100}
                step={1}
                value={zoomPercent}
                disabled={!doc.open}
                aria-label="확대/축소"
                onChange={(event) => void changeZoom(Number(event.target.value) / 100)}
                className="h-[22px] w-[88px] accent-sky-600 disabled:opacity-40"
              />
              <button
                type="button"
                className={barBtnClass}
                title="확대"
                disabled={!doc.open || zoom >= MAX_ZOOM}
                onClick={() => void changeZoom(zoom * ZOOM_STEP)}
              >
                +
              </button>
              <input
                list="editor-zoom-presets"
                aria-label="확대 비율"
                disabled={!doc.open}
                key={`zoom-${zoomPercent}`}
                defaultValue={`${zoomPercent}%`}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.currentTarget.blur();
                    applyZoomPercent(event.currentTarget.value);
                  }
                }}
                onBlur={(event) => applyZoomPercent(event.currentTarget.value)}
                className="h-[22px] w-[76px] rounded border border-slate-300 bg-white px-1 text-center text-[12px] text-slate-700 outline-none focus:border-app-accent disabled:opacity-50"
              />
              <datalist id="editor-zoom-presets">
                {ZOOM_PRESETS.map((value) => (
                  <option key={value} value={`${value}%`} />
                ))}
              </datalist>
            </div>
          </footer>
        </div>
      </div>

      <HwpConvertDialog
        open={hwpOpen}
        onClose={() => setHwpOpen(false)}
        onConverted={(openPath) => {
          setHwpOpen(false);
          if (openPath) void openFileTarget(openPath);
        }}
      />
      <MergePdfDialog
        open={mergeOpen}
        onClose={() => setMergeOpen(false)}
        onMerged={(filePath) => {
          setMergeOpen(false);
          void openFileTarget(filePath);
        }}
      />
      <ReduceSizeDialog
        open={reduceOpen}
        onClose={() => setReduceOpen(false)}
        onApply={(options) => void applyReduceSize(options)}
      />
      <PageNumberDialog
        open={pageNumberOpen}
        pageCount={doc.pageCount || 0}
        onClose={() => setPageNumberOpen(false)}
        onApply={(options) => void applyPageNumbers(options)}
        loadApplied={async () => (await api('pdf.pageNumberOptions')).options}
      />
      <ExportImagesDialog
        open={Boolean(exportScope)}
        pageCount={doc.pageCount || 0}
        indices={exportScope?.indices ?? null}
        onClose={() => setExportScope(null)}
        onApply={(options) => void runExportImages(exportScope, options)}
      />
      <OcrDialog
        open={Boolean(ocrScope)}
        pageCount={doc.pageCount || 0}
        indices={ocrScope?.indices ?? null}
        onClose={() => setOcrScope(null)}
        onApply={(payload) => void handleOcrApply(payload, ocrScope)}
      />
      <PasswordOpenDialog
        open={Boolean(passwordPath)}
        rejected={passwordRejected}
        onSubmit={(nextPassword) => void submitPassword(nextPassword)}
        onCancel={cancelPassword}
      />
      <PasswordSetDialog
        open={passwordDialogOpen}
        onClose={() => setPasswordDialogOpen(false)}
        onApplied={onPasswordApplied}
      />
      <PiiRemoveDialog
        open={piiScope !== undefined}
        pageIndices={piiScope ?? null}
        onClose={closePiiDialog}
        onPreview={previewPiiHit}
        onApply={(hits, style) => void applyPiiRedact(hits, style)}
      />

      {/* 전체화면 종료 버튼 */}
      {fullscreen && (
        <div className="fixed inset-0 z-[1000] pointer-events-none">
          {showFullscreenExit && (
            <button
              type="button"
              className="pointer-events-auto absolute top-7 left-1/2 -translate-x-1/2 h-9 w-9 rounded-full bg-white text-black hover:bg-gray-100 flex items-center justify-center transition-colors"
              onClick={() => setFullscreen(false)}
              title="전체 화면 해제 (ESC)"
              aria-label="전체 화면 해제"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
