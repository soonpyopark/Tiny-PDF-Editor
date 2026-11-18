import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useDialog } from '../../context/DialogContext.jsx';
import { api as apiRaw, engineScope } from '../../lib/apiClient.js';
import { formatMb } from '../../lib/format.js';
import { enterFullscreen, useFullscreen } from '../../lib/fullscreen.js';
import Toast from '../../components/common/Toast.jsx';
import { useRegisterEditorCommands } from './editorCommands.jsx';
import PageSide, { PanelToggleTab } from './PageSide.jsx';
import { ReduceSizeDialog, SearchDropdown } from './editorDialogs.jsx';
import PageNumberDialog from './PageNumberDialog.jsx';
import PrintDialog from './PrintDialog.jsx';
import ExportImagesDialog from './ExportImagesDialog.jsx';
import PdfConvertDialog from './PdfConvertDialog.jsx';
import PasswordOpenDialog from './PasswordOpenDialog.jsx';
import PasswordSetDialog from './PasswordSetDialog.jsx';
import PiiRemoveDialog from './PiiRemoveDialog.jsx';
import OcrDialog from './OcrDialog.jsx';
import TextMarkupLayer from './TextMarkupLayer.jsx';
import ImageLayer from './ImageLayer.jsx';
import ImageToolbar from './ImageToolbar.jsx';
import { noteCopyKind, useImageEditing } from './useImageEditing.js';
import DrawLayer from './draw/DrawLayer.jsx';
import DrawToolbar from './draw/DrawToolbar.jsx';
import ShapeLayer from './draw/ShapeLayer.jsx';
import { hexToRgb01, loadDrawState, saveDrawState } from './draw/drawSettings.js';
import { SELECT_TOOL, SHAPE_TOOL_IDS, styleGroupOf, styleToParams } from './draw/shapeSettings.js';
import { useShapeEditing } from './draw/useShapeEditing.js';
import TerminalPanel from './TerminalPanel.jsx';

const EMPTY_DOC = { open: false, name: '', path: null, pageCount: 0, modified: false };
const MIN_ZOOM = 0.2;
const MAX_ZOOM = 5;
const ZOOM_STEP = 1.1;
const ZOOM_PRESETS = [25, 50, 75, 100, 125, 150, 200, 250, 300, 350, 400, 500];

/**
 * 하단 막대의 왼쪽 칸 너비(px) = 왼쪽 탭(44) + 썸네일 패널(256). 패널을 접어도 이 폭을 비워 두어 오른쪽 단추가 움직이지 않는다.
 * 단추 줄(약 670) + 좌우 여백이 한 줄로 유지되는 너비가 FOOTER_CONTROLS_MIN_WIDTH 이고,
 * 창은 이 둘의 합보다 좁아지지 않는다.
 */
const SIDE_FOOTER_WIDTH = 300;
const FOOTER_CONTROLS_MIN_WIDTH = 690;
const MIN_CONTENT_WIDTH = SIDE_FOOTER_WIDTH + FOOTER_CONTROLS_MIN_WIDTH;

/** 본문 가운데 진행 안내에 보여 줄 "3 / 20" 과 처리 중인 대상 이름. */
function progressDetail(progress) {
  if (!progress.total) return { count: '', name: progress.note || '' };
  if (progress.op === 'insert') {
    return {
      count: `${Math.min(progress.current + 1, progress.total)} / ${progress.total}`,
      name: progress.label || '',
    };
  }
  return { count: progress.label || `${progress.current} / ${progress.total}`, name: '' };
}

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

/**
 * Neo editor: Tiny PDF Editor features via the headless engine.
 * 한 탭 = 이 컴포넌트 인스턴스 하나 = PDF 엔진 세션 하나 (DocumentTabs 가 관리).
 * @param {{
 *   tabKey?: string,
 *   active?: boolean,
 *   initialPath?: string,
 *   onDocChange?: (tabKey: string, state: { name: string, open: boolean, modified: boolean, fullscreen: boolean }) => void,
 *   onOpenInNewTab?: (filePath: string) => void,
 *   onRegisterControls?: (tabKey: string, controls: { confirmClose: () => Promise<boolean>, closeDoc: () => void, openPath: (filePath: string) => Promise<void> } | null) => void,
 * }} props
 */
export default function EditorPage({
  tabKey = '',
  active = true,
  initialPath = '',
  onDocChange,
  onOpenInNewTab,
  onRegisterControls,
}) {
  const dialog = useDialog();
  // 이 탭의 엔진 세션으로 보내는 요청. 아래 본문의 api(...) 호출은 모두 이 함수를 쓴다.
  const api = (name, body) => apiRaw(name, body, { tab: tabKey });
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
  // 파일 추가·이미지 저장처럼 오래 걸리는 작업의 진행 상황: { op, title, label, current, total, blocking, cancelling, at }
  const [progress, setProgress] = useState(/** @type {any} */ (null));
  const [error, setError] = useState('');
  const [toast, setToast] = useState(/** @type {{ message: string, type: 'error' | 'success' | 'info' | 'warning' } | null} */ (null));
  // 하단 "터미널": 오래 걸리는 작업의 세부 진행 로그가 쌓인다. 진행 안내의 [세부진행상황 보기] 로 연다.
  const [terminal, setTerminal] = useState({ open: false, expanded: true, lines: /** @type {string[]} */ ([]) });

  const appendTerminal = useCallback((line) => {
    setTerminal((prev) => ({ ...prev, lines: [...prev.lines, line] }));
  }, []);

  // 에러가 발생하면 우측 하단 토스트로 표시
  useEffect(() => {
    if (error) setToast({ message: error, type: 'error' });
  }, [error]);

  useEffect(() => {
    const subscribe = window.frame?.onPdfLog;
    if (typeof subscribe !== 'function') return undefined;
    const myScope = engineScope(tabKey);
    return subscribe((/** @type {{ message?: string, windowId?: string, progress?: any }} */ payload) => {
      // 다른 문서 창/탭의 엔진 로그는 이 터미널에 섞지 않는다.
      if (payload?.windowId !== myScope) return;
      if (payload.message) {
        appendTerminal(payload.message);
        // 쪽·파일 수를 아직 모르는 단계(준비 중 등)에서는 최근 로그를 안내 카드에 보여 준다.
        setProgress((prev) => (prev ? { ...prev, note: String(payload.message).trim() } : prev));
      }
      const p = payload.progress;
      if (!p) return;
      if (p.done) {
        setProgress((prev) => (prev && prev.op === p.op ? null : prev));
        return;
      }
      // 시작해 둔 작업(withProgress)의 진행만 갱신한다. 대화상자(병합 등)가 일으킨 진행은 그 대화상자가 맡는다.
      setProgress((prev) =>
        prev && prev.op === p.op
          ? {
              ...prev,
              current: p.current,
              total: p.total,
              label: p.label,
              // 첫 진행 알림이 와야(= 파일 선택·폴더 선택 창이 닫히고 실제 작업이 시작돼야) 본문을 흐리게 한다.
              blocking: true,
            }
          : prev,
      );
      // 이 작업들은 엔진이 따로 로그를 남기지 않으므로 진행 알림을 터미널에도 적는다.
      if (p.label && (p.op === 'insert' || p.op === 'exportImages' || p.op === 'exportPagesImages')) {
        appendTerminal(p.op === 'insert' ? `(${Math.min(p.current + 1, p.total)}/${p.total}) ${p.label}` : p.label);
      }
    });
  }, [appendTerminal, tabKey]);

  const cancelRequestedRef = useRef(false);

  /** 오래 걸리는 작업을 진행 표시와 함께 실행한다. 끝나면(결과 화면 반영까지) 표시를 지운다. */
  async function withProgress(meta, run) {
    cancelRequestedRef.current = false;
    // immediate: 파일·폴더 선택 창이 없는 작업은 시작하자마자 본문을 흐리게 하고 안내를 보여 준다.
    setProgress({
      op: meta.op,
      title: meta.title,
      label: '',
      note: '',
      current: 0,
      total: 0,
      blocking: Boolean(meta.immediate),
      cancelling: false,
      at: meta.at ?? 0,
    });
    setTerminal((prev) => ({ ...prev, lines: [`> ${meta.title}`] }));
    try {
      return await run();
    } finally {
      setProgress(null);
    }
  }

  /** 진행 중인 작업을 멈추게 한다. 엔진이 다음 파일/쪽 사이에서 멈추고, 그때까지 한 것은 남는다. */
  function cancelProgress() {
    cancelRequestedRef.current = true;
    setProgress((prev) => (prev && !prev.cancelling ? { ...prev, cancelling: true } : prev));
    void api('pdf.cancel', {}).catch(() => {});
  }

  // 넘어온 파일(?open= 또는 새 탭으로 연 파일)을 이 탭의 엔진으로 연다.
  useEffect(() => {
    if (!initialPath) return;
    void openRecent(initialPath);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [passwordPath, setPasswordPath] = useState('');
  const [passwordRejected, setPasswordRejected] = useState(false);
  // 썸네일·메뉴로 파일 추가할 때 비밀번호를 기다리게 한다. resolve(password | null).
  const passwordWaiterRef = useRef(/** @type {null | ((value: string | null) => void)} */ (null));
  const [facing, setFacing] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState(/** @type {any[]} */ ([]));
  // 마지막으로 Enter 로 실행한 검색어. 입력만 바뀌고 아직 Enter 를 안 누른 상태와 구분한다.
  const [searchRanQuery, setSearchRanQuery] = useState('');
  const [searchIndex, setSearchIndex] = useState(0);
  // 그리기 모드: 켜져 있는 동안 쪽 위에 DrawLayer 가 올라가고, 손을 뗀 획은 PDF 잉크 주석으로 들어간다.
  const [drawOn, setDrawOn] = useState(false);
  const [drawState, setDrawState] = useState(loadDrawState);
  const drawOnRef = useRef(false);
  drawOnRef.current = drawOn;
  // 엔진 반영은 순서대로 한 줄로 처리한다 (획이 겹쳐 들어와도 순서가 뒤바뀌지 않게).
  const inkQueueRef = useRef(/** @type {Promise<void>} */ (Promise.resolve()));
  const lastInkAtRef = useRef(0);
  const thumbTimersRef = useRef(/** @type {Record<number, number>} */ ({}));
  // 앞 획을 뗀 뒤 이 시간 안에 다음 획을 시작하면 되돌리기 한 단계로 묶는다 (글씨 한 자의 여러 획을 한 번에 취소).
  const INK_GROUP_MS = 800;

  useEffect(() => {
    saveDrawState(drawState);
  }, [drawState]);

  // Esc 로 그리기 끝내기.
  useEffect(() => {
    if (!drawOn || !active) return undefined;
    function onKeyDown(event) {
      if (event.key !== 'Escape') return;
      // 글자를 입력하는 칸에서는 건드리지 않는다. 슬라이더 같은 조절 칸은 해당 없음.
      const el = event.target;
      if (el instanceof HTMLTextAreaElement) return;
      if (el instanceof HTMLInputElement && !['range', 'checkbox', 'radio', 'button', 'color'].includes(el.type)) return;
      event.preventDefault();
      void endDrawing();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawOn, active]);

  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  // undefined: 대화상자 닫힘 / null: 전체 페이지 / number[]: 선택한 페이지만
  const [piiScope, setPiiScope] = useState(/** @type {undefined | null | number[]} */ (undefined));
  // 개인정보 미리보기 빨간 상자 (0..1 비율). 현재 쪽에만 그린다.
  const [reviewRects, setReviewRects] = useState(
    /** @type {null | { pageIndex: number, focus: number[][], others: number[][] }} */ (null),
  );
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [reduceOpen, setReduceOpen] = useState(false);
  const [reduceSourceDpi, setReduceSourceDpi] = useState(null);
  const [pageNumberOpen, setPageNumberOpen] = useState(false);
  // 이미지로 저장 옵션창 범위: null 이면 닫힘, { indices: null } 은 문서 전체, { indices: [..] } 은 선택 페이지.
  const [exportScope, setExportScope] = useState(null);
  // OCR 옵션창: null 이면 닫힘, { indices: null } 은 범위 입력 모드, { indices: [..] } 은 썸네일 선택 모드.
  const [ocrScope, setOcrScope] = useState(null);
  const [printScope, setPrintScope] = useState(/** @type {{ indices: number[] | null } | null} */ (null));
  // 전체화면은 앱 전체가 공유한다 (메뉴·F11·종료 버튼은 AppShell 이 처리).
  const fullscreen = useFullscreen();
  // 전체화면에서 왼쪽 패널은 숨기되 토글 탭은 남기고, 탭을 누르면 패널을 잠시 펼친다 (원본 동작).
  const [fullscreenPanelOpen, setFullscreenPanelOpen] = useState(false);
  useEffect(() => {
    if (!fullscreen) setFullscreenPanelOpen(false);
  }, [fullscreen]);
  const [convertOpen, setConvertOpen] = useState(false);
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

  // 이미지 넣기·다시 고치기(선택/이동/크기/복사/투명 배경/자르기 …). 확정 전에는 PDF 가 바뀌지 않는다.
  const imageEdit = useImageEditing({
    api,
    doc,
    pageIndex,
    docRef,
    drawOnRef,
    pageIndexRef,
    zoomRef,
    active,
    setError,
    endDrawing,
    getPageBox: (index) => {
      const [w, h] = pageSizes[index] ?? FALLBACK_PAGE_PT;
      return [0, 0, w, h];
    },
    refreshPage: (nextDoc, index) => refreshInkPage(nextDoc, index),
    applyDocResult: (result, index) => applyDocResult(result, index),
  });
  const imageEditRef = useRef(imageEdit);
  imageEditRef.current = imageEdit;

  // 도형(선·화살표·사각형·…·텍스트 상자): 그리기 모드에서 '선택' 또는 도형 도구일 때만 켠다.
  const shapeToolOn = drawOn && (drawState.tool === SELECT_TOOL || SHAPE_TOOL_IDS.includes(drawState.tool));
  const shapeEdit = useShapeEditing({
    api,
    doc,
    pageIndex,
    enabled: shapeToolOn,
    setError,
    refreshPage: (nextDoc, index) => refreshInkPage(nextDoc, index),
  });
  const shapeEditRef = useRef(shapeEdit);
  shapeEditRef.current = shapeEdit;
  const newShapeParams = SHAPE_TOOL_IDS.includes(drawState.tool)
    ? styleToParams(drawState.tool, drawState.shapes[styleGroupOf(drawState.tool)])
    : null;

  useEffect(() => {
    let cancelled = false;
    api('pdf.status')
      .then((data) => {
        if (cancelled) return;
        setStatus(data);
        // 원본 Tiny 처럼 실행하면 빈 문서 탭을 연다. 이미 열린 문서가 있거나 열 파일(?open=)이 있는 창은 건너뛴다.
        // initialPath 가 있으면 넘어온 파일을 연다. 그 탭에는 빈 문서를 만들지 않는다.
        if (data.ready && !data.doc?.open && !initialPath) {
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
      // loadPage 가 렌더 전에 바로 이어지므로, 쪽 수가 바뀐 새 문서를 ref 에 먼저 반영한다(삭제 뒤 옛 쪽 번호를 그리다 실패하지 않게).
      docRef.current = nextDoc;
      setDoc(nextDoc);
      setPageIndex(index);
      pageMapRef.current = { zoom: 0, map: {} };
      setPageSrcs({ zoom: 0, map: {} });
      setPageSizes([]);
      setThumbs(Array.from({ length: nextDoc.pageCount || 0 }, () => ''));
      setMarkups(nextDoc.open ? null : []);
      imageEditRef.current?.reset();
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
      // 본문 그림이 실패해도 썸네일은 계속 채운다(한쪽 오류가 썸네일 전체를 막지 않게).
      try {
        await loadPage(index, zoomRef.current, token);
      } catch (err) {
        if (requestId.current === token) setError(err instanceof Error ? err.message : '페이지를 그리지 못했습니다.');
      }
      for (let i = 0; i < nextDoc.pageCount; i += 1) {
        if (requestId.current !== token) return;
        let image;
        try {
          image = await api('pdf.render', { index: i, thumb: true });
        } catch {
          continue;
        }
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

  /** 비밀번호 창을 띄우고, 확인되면 암호 문자열을, 취소면 null 을 돌려준다. */
  function promptPassword(filePath, rejected = false) {
    return new Promise((resolve) => {
      // 이전 대기가 있으면 취소로 끝낸다.
      if (passwordWaiterRef.current) passwordWaiterRef.current(null);
      passwordWaiterRef.current = resolve;
      setPasswordPath(filePath);
      setPasswordRejected(Boolean(rejected));
    });
  }

  function finishPasswordPrompt(value) {
    const resolve = passwordWaiterRef.current;
    passwordWaiterRef.current = null;
    setPasswordPath('');
    setPasswordRejected(false);
    if (resolve) resolve(value);
  }

  // 비밀번호 확인 대화상자. 파일 추가 대기 중이면 암호만 검사해 넘기고, 아니면 문서를 연다.
  async function submitPassword(nextPassword) {
    if (!passwordPath || !nextPassword) return;
    setError('');
    try {
      if (passwordWaiterRef.current) {
        const check = await api('pdf.mergePreview', { path: passwordPath, password: nextPassword });
        if (check.needsPassword) {
          setPasswordRejected(true);
          return;
        }
        finishPasswordPrompt(nextPassword);
        return;
      }
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
    if (passwordWaiterRef.current) {
      finishPasswordPrompt(null);
      return;
    }
    setPasswordPath('');
    setPasswordRejected(false);
  }

  /**
   * 추가할 파일 중 잠긴 PDF 는 비밀번호를 먼저 받는다.
   * 취소한 잠긴 파일은 빼고, 나머지는 passwords 와 함께 돌려준다.
   */
  async function collectPasswordsForInsert(paths) {
    const list = (paths || []).map(String).filter(Boolean);
    if (!list.length) return { paths: [], passwords: {} };
    const pdfPaths = list.filter((path) => path.toLowerCase().endsWith('.pdf'));
    /** @type {Set<string>} */
    const locked = new Set();
    if (pdfPaths.length) {
      try {
        const inspected = await api('pdf.mergeInspect', { paths: pdfPaths, passwords: {} });
        for (const item of inspected.items || []) {
          if (item?.needsPassword && item.path) locked.add(String(item.path));
        }
      } catch {
        // 검사에 실패해도 insert 가 다시 알려 줄 수 있으니, 잠긴 목록 없이 진행한다.
      }
    }
    /** @type {Record<string, string>} */
    const passwords = {};
    const kept = [];
    let skipped = 0;
    for (const path of list) {
      if (!locked.has(path)) {
        kept.push(path);
        continue;
      }
      let rejected = false;
      let accepted = false;
      while (!accepted) {
        const password = await promptPassword(path, rejected);
        if (!password) {
          skipped += 1;
          break;
        }
        passwords[path] = password;
        kept.push(path);
        accepted = true;
      }
    }
    return { paths: kept, passwords, skipped };
  }

  /** 경로를 받아(필요하면 비밀번호를 모은 뒤) 문서에 끼워 넣는다. */
  async function insertPathsAt(rawPaths, atIndex) {
    const prepared = await collectPasswordsForInsert(rawPaths);
    if (!prepared.paths.length) {
      if (prepared.skipped) {
        setToast({ message: '비밀번호가 필요한 파일은 추가하지 않았습니다.', type: 'info' });
      }
      return;
    }
    if (prepared.skipped) {
      setToast({
        message: `비밀번호를 입력하지 않은 파일 ${prepared.skipped}개는 건너뛰었습니다.`,
        type: 'info',
      });
    }
    await withProgress({ op: 'insert', title: '파일 추가 중', at: atIndex }, async () => {
      const result = await api('pdf.insert', {
        index: atIndex,
        paths: prepared.paths,
        passwords: prepared.passwords,
      });
      if (result.canceled) return;
      if (result.needsPassword) {
        // 검사 후에도 암호가 틀리거나 빠진 경우. 이미 들어간 쪽이 있으면 화면에 맞춘다.
        if (result.doc) await applyDocResult(result, atIndex);
        setToast({
          message: `${String(result.path || '').split(/[\\/]/).pop() || '파일'}은 비밀번호가 필요해 추가하지 못했습니다.`,
          type: 'warning',
        });
        return;
      }
      await applyDocResult(result, atIndex);
      noticeStopped(result);
    });
  }

  // 쪽으로 이동: 쪽 그림을 바꾸는 대신 그 쪽의 자리로 스크롤한다. 근처 쪽 그리기는 effect 가 맡는다.
  function goTo(index) {
    if (!doc.open || index < 0 || index >= doc.pageCount) return;
    const target = facing ? index - (index % 2) : index;
    setError('');
    setPageIndex(target);
    scrollToPage(target);
  }

  // 검색 결과로 이동: 해당 쪽으로 간 뒤, 찾은 글자가 화면 가운데 오도록 본문을 움직인다.
  // 이미 화면 안(가장자리 여유 포함)에 보이면 그대로 둔다.
  function goToHit(hit) {
    if (!hit) return;
    goTo(hit.pageIndex);
    const view = viewRef.current;
    const el = view?.querySelector(`[data-page="${hit.pageIndex}"]`);
    if (!view || !el) return;
    const [, ptH] = pageSizes[hit.pageIndex] ?? FALLBACK_PAGE_PT;
    const pageRect = el.getBoundingClientRect();
    const viewRect = view.getBoundingClientRect();
    const scale = pageRect.height / Math.max(1, ptH);
    const originX = pageRect.left - viewRect.left + view.scrollLeft;
    const originY = pageRect.top - viewRect.top + view.scrollTop;
    const left = originX + hit.x0 * scale;
    const right = originX + hit.x1 * scale;
    const top = originY + hit.y0 * scale;
    const bottom = originY + hit.y1 * scale;
    const margin = 48;
    const visible =
      top >= view.scrollTop + margin &&
      bottom <= view.scrollTop + view.clientHeight - margin &&
      left >= view.scrollLeft + margin &&
      right <= view.scrollLeft + view.clientWidth - margin;
    if (visible) return;
    view.scrollTo({
      top: Math.max(0, (top + bottom) / 2 - view.clientHeight / 2),
      left: Math.max(0, (left + right) / 2 - view.clientWidth / 2),
      behavior: 'auto',
    });
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

  /** 저장했으면 true. 저장 대화상자를 취소하거나 실패하면 false. */
  async function save() {
    setError('');
    try {
      await flushInk();
      const saved = doc.path ? await api('pdf.save') : await api('pdf.pickSave');
      if (saved.canceled) return false;
      setDoc(saved.doc);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장하지 못했습니다.');
      return false;
    }
  }

  /** 다른 이름으로 저장했으면 true. 대화상자를 취소하거나 실패하면 false. */
  async function saveAs() {
    setError('');
    try {
      await flushInk();
      const saved = await api('pdf.pickSave');
      if (saved.canceled) return false;
      setDoc(saved.doc);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장하지 못했습니다.');
      return false;
    }
  }

  async function closeDoc() {
    // 수정된 문서는 버리기 전에 저장 여부를 먼저 묻는다 (탭 X · 파일 > 닫기 공통).
    const proceed = await confirmUnsavedChanges({
      title: '저장 여부',
      body: `'${docRef.current.name}'의 변경 사항을 저장하시겠습니까?`,
      extraLabel: '저장하지 않고 닫기',
    });
    if (!proceed) return;
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

  /**
   * 수정된 문서를 버리기 전에 저장 여부를 묻는다. 진행해도 되면 true.
   * '취소'를 누르거나, 저장을 골랐는데 저장이 취소·실패하면 false.
   */
  async function confirmUnsavedChanges({ title, body, extraLabel }) {
    // 방금 그린 획이 아직 엔진에 들어가는 중일 수 있다. 끝난 뒤의 수정 여부로 판단한다.
    await flushInk();
    if (!docRef.current.modified) return true;
    const choice = await dialog.choose({
      title,
      body,
      primaryLabel: '저장',
      secondaryLabel: '다른 이름으로 저장',
      extraLabel,
      cancelLabel: '취소',
    });
    if (choice === 'primary') return save();
    if (choice === 'secondary') return saveAs();
    return choice === 'extra';
  }

  async function newDoc() {
    setError('');
    const proceed = await confirmUnsavedChanges({
      title: '저장 여부',
      body: '현재 문서가 수정되었습니다.\n저장하시겠습니까?',
      extraLabel: '저장하지 않고 열기',
    });
    if (!proceed) return;
    try {
      const created = await api('pdf.new');
      await showDocument(created.doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : '새 문서를 만들지 못했습니다.');
    }
  }

  /** 취소로 중간에 멈췄다면 알려 준다 (그때까지 추가된 것은 남아 있고 되돌리기로 한 번에 취소할 수 있다). */
  function noticeStopped(result) {
    if (result?.stopped) {
      setToast({ message: `취소했습니다. ${result.added ?? 0}쪽까지 추가되었고, Ctrl+Z 로 되돌릴 수 있습니다.`, type: 'info' });
    }
  }

  async function insertFiles() {
    setError('');
    try {
      const picked = await api('pdf.insert', { pickOnly: true });
      if (picked.canceled || !picked.paths?.length) return;
      await insertPathsAt(picked.paths, pageIndex + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '파일을 추가하지 못했습니다.');
    }
  }

  // PDF 변환(병합 / 개별 변환): 대화상자에서 파일을 모아 저장한 뒤, 병합 결과 또는 (원하면) 첫 변환 결과를 연다.
  function convertFiles() {
    setError('');
    setConvertOpen(true);
  }

  /**
   * 원본 _open_paths: 문서가 열려 있고 '새 창으로 열기'이면 새 창에서 연다.
   * 그 밖에는 이 창에서 연다. 브라우저(창 기능 없음)는 항상 이 창에서 연다.
   */
  /**
   * 원본 _is_effectively_empty: 경로·수정·페이지가 없는 문서는 빈 문서로 본다.
   * 엔진은 빈 문서도 open: true 로 돌려주므로 open 만으로 판단하면 안 된다.
   */
  function isEffectivelyEmpty(current) {
    return !current.open || (!current.path && !current.modified && (current.pageCount || 0) === 0);
  }

  /**
   * 파일 열기 라우팅 (원본 _open_paths 와 같은 순서)
   * 1) 빈 문서 상태 -> 이 창에서 바로 연다.
   * 2) 문서가 열려 있고 설정이 '새 창' -> 새 창으로 연다.
   * 3) 그 밖 -> 이 창에서 연다 (현재 문서를 교체하므로 수정 확인을 먼저 받는다).
   */
  async function openFileTarget(filePath) {
    const native = window.frame;
    if (!isEffectivelyEmpty(docRef.current)) {
      let openInNewWindow = false;
      try {
        ({ openInNewWindow } = await api('pdf.openTargetGet'));
      } catch {
        // 설정을 읽지 못하면 이 창에서 연다.
      }
      if (openInNewWindow && native?.openDocumentWindow) {
        await native.openDocumentWindow(filePath);
        return;
      }
      // 새 탭: 현재 탭은 그대로 두고 이 창에 탭을 하나 더 만든다. 수정 확인은 필요 없다.
      if (onOpenInNewTab) {
        onOpenInNewTab(filePath);
        return;
      }
      const proceed = await confirmUnsavedChanges({
        title: '저장 여부',
        body: '현재 문서가 수정되었습니다.\n저장하시겠습니까?',
        extraLabel: '저장하지 않고 열기',
      });
      if (!proceed) return;
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
      // HWP/HWPX 파일을 분리: 자동 변환 후 결과 PDF와 나머지 파일을 함께 추가
      if (action.type === 'insertFiles' && action.paths?.length) {
        const hwpFiles = [];
        const otherFiles = [];
        for (const filePath of action.paths) {
          const ext = filePath.toLowerCase().slice((filePath.lastIndexOf('.') - 1 >>> 0) + 2);
          if (ext === 'hwp' || ext === 'hwpx') {
            hwpFiles.push(filePath);
          } else {
            otherFiles.push(filePath);
          }
        }
        // HWP 파일을 자동 변환
        if (hwpFiles.length) {
          try {
            const convertedPdfs = [];
            let stopped = false;
            await withProgress({ op: 'hwpConvert', title: '한글 문서 변환 중', immediate: true }, async () => {
              for (let k = 0; k < hwpFiles.length; k += 1) {
                // 한글 변환은 중간에 끊을 수 없어서, 취소는 지금 파일이 끝난 뒤 다음 파일부터 멈춘다.
                if (cancelRequestedRef.current) {
                  stopped = true;
                  break;
                }
                const hwpPath = hwpFiles[k];
                const name = hwpPath.split(/[\\/]/).pop();
                setProgress((prev) => (prev ? { ...prev, current: k, total: hwpFiles.length, label: `${k + 1} / ${hwpFiles.length}`, note: name } : prev));
                appendTerminal(`(${k + 1}/${hwpFiles.length}) ${name}`);
                const result = await api('pdf.hwpConvertQuick', { source: hwpPath });
                convertedPdfs.push(result.path);
              }
            });
            if (stopped) {
              setToast({ message: '취소했습니다. 파일은 추가되지 않았습니다.', type: 'info' });
              return;
            }
            // 변환된 PDF + 나머지 파일을 모두 추가
            action.paths = [...convertedPdfs, ...otherFiles];
            if (!action.paths.length) return;
          } catch (err) {
            const message = err instanceof Error ? err.message : '한글 문서 변환에 실패했습니다.';
            setError(message);
            return;
          }
        }
      }
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
          const paths = Array.isArray(action.paths) ? action.paths : [];
          if (!paths.length) {
            const picked = await api('pdf.insert', { pickOnly: true });
            if (picked.canceled || !picked.paths?.length) return;
            await insertPathsAt(picked.paths, targetIndex);
          } else {
            await insertPathsAt(paths, targetIndex);
          }
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
          await openPrint(indices);
          return;
        }
        case 'printAll':
          await openPrint(null);
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
      await flushInk();
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
    try {
      const exportOp = scope?.indices ? 'exportPagesImages' : 'exportImages';
      await withProgress({ op: exportOp, title: '이미지 저장 중' }, async () => {
        if (scope?.indices) {
          const result = await api('pdf.exportPagesImages', { indices: scope.indices, options });
          if (result.canceled) return;
          void dialog.alert({
            title: '이미지로 저장',
            body: `${result.stopped ? `작업을 취소했습니다. ${result.count}개 이미지가 저장되어 있습니다.` : `${result.count}개 이미지를 저장했습니다.`}\n${result.dir}`,
          });
        } else {
          // 완료 후 폴더 열기 질문은 Electron 쪽 대화상자에서 처리한다.
          await api('pdf.exportImages', { options });
        }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '이미지로 저장하지 못했습니다.');
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
      if (hits.length) goToHit(hits[0]);
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
    goToHit(searchHits[next]);
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
      // 이미지를 고르고 있으면 복사·잘라내기는 이미지에, 마지막에 복사한 게 이미지면 붙여넣기도 이미지에 한다.
      if (kind !== 'paste' && imageEdit.hasSelection()) {
        if (kind === 'copy') await imageEdit.copySelected();
        else await imageEdit.cutSelected();
        return;
      }
      if (kind === 'paste' && imageEdit.hasClipboard()) {
        await imageEdit.pasteClip();
        return;
      }
      noteCopyKind('page');
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
    try {
      await withProgress({ op: 'reduceSize', title: '용량 줄이는 중', immediate: true }, async () => {
        const result = await api('pdf.reduceSize', options);
        if (result.stopped) {
          setToast({ message: '용량 줄이기를 취소했습니다. 문서는 그대로입니다.', type: 'info' });
          return;
        }
        await applyDocResult(result, pageIndex);
        const sizeText = `${formatMb(result.before || 0)} → ${formatMb(result.after || 0)}`;
        appendTerminal(`완료: ${sizeText}`);
        void dialog.alert({ title: '용량 줄이기', body: sizeText });
      });
    } catch (err) {
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
    try {
      const body =
        mode === 'all'
          ? { mode: 'all' }
          : mode === 'selected'
            ? { indices: indices?.length ? indices : [pageIndex] }
            : { mode: 'current', index: pageIndex };
      await withProgress({ op: 'ocr', title: 'OCR 중', immediate: true }, async () => {
        const result = await api('pdf.ocr', body);
        await applyDocResult(result, pageIndex);
        appendTerminal(
          `완료: ${result.applied}페이지, ${result.lines}줄 (건너뜀 ${result.skipped}, 실패 ${result.failed})`,
        );
        if (result.stopped) {
          setToast({ message: `OCR을 취소했습니다. ${result.applied}쪽까지 인식되었고, Ctrl+Z 로 되돌릴 수 있습니다.`, type: 'info' });
        } else {
          void dialog.alert({ title: 'OCR', body: ocrResultMessage(result) });
        }
      });
    } catch (err) {
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
      await withProgress({ op: 'piiRedact', title: '개인정보 제거 중', immediate: true }, async () => {
        const result = await api('pdf.piiRedact', { hits, style });
        if (result.stopped) {
          setToast({ message: '개인정보 제거를 취소했습니다. 문서는 그대로입니다.', type: 'info' });
          return;
        }
        await applyDocResult(result, pageIndex);
        const summary = countText(result.hitCount, result.areaCount);
        appendTerminal(`완료: ${summary}를 제거했습니다.`);
        void dialog.alert({
          title: '개인정보 제거',
          body: `${summary}의 원본 내용을 제거했습니다.\n저장 전에 결과를 확인하세요.`,
        });
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : '개인정보를 제거하지 못했습니다.';
      appendTerminal(`오류: ${message}`);
      setError(message);
    }
  }

  // 진행 중인 그리기 반영과 편집 중인 이미지 확정이 모두 끝날 때까지 기다린다. 저장·되돌리기·닫기 전에 부른다.
  async function flushInk() {
    await imageEditRef.current?.commit();
    await shapeEditRef.current?.commit();
    await inkQueueRef.current;
  }

  function scheduleInkThumb(index) {
    window.clearTimeout(thumbTimersRef.current[index]);
    thumbTimersRef.current[index] = window.setTimeout(() => {
      api('pdf.render', { index, thumb: true })
        .then((thumb) => {
          setThumbs((prev) => {
            if (index >= prev.length) return prev;
            const copy = prev.slice();
            copy[index] = `data:image/png;base64,${thumb.png}`;
            return copy;
          });
        })
        .catch(() => {});
    }, 700);
  }

  // 그린 쪽 하나만 다시 그린다. (형광펜·밑줄처럼 주변 쪽까지 새로 그리면 획마다 너무 느리다.)
  async function refreshInkPage(nextDoc, index) {
    setDoc(nextDoc);
    docRef.current = nextDoc; // 렌더 전에 저장 여부 확인이 읽어도 최신이게
    const z = zoomRef.current;
    const image = await api('pdf.render', { index, zoom: z });
    if (zoomRef.current === z) {
      commitPages(z, (map) => ({ ...map, [index]: `data:image/png;base64,${image.png}` }));
    }
    scheduleInkThumb(index);
  }

  function commitInk(index, points, style, timing) {
    const rounded = points.map(([x, y]) => [Math.round(x * 100) / 100, Math.round(y * 100) / 100]);
    // 앞 획에서 손을 뗀 뒤 곧바로 다음 획을 시작했으면 되돌리기 한 단계로 묶는다.
    // 판단은 순서가 섞이지 않게 줄에 서기 전에 한다. (엔진도 그 사이 다른 편집이 있었으면 묶지 않는다.)
    const joined = timing.startedAt - lastInkAtRef.current < INK_GROUP_MS;
    lastInkAtRef.current = timing.endedAt;
    const job = inkQueueRef.current
      .then(async () => {
        const result = await api('pdf.inkAdd', {
          pageIndex: index,
          strokes: [rounded],
          color: hexToRgb01(style.color),
          width: style.width,
          opacity: style.opacity,
          continueGroup: joined,
        });
        await refreshInkPage(result.doc, index);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : '그리지 못했습니다.');
      });
    inkQueueRef.current = job;
    return job;
  }

  // 지우개: 드래그 한 번(=여러 조각 요청)을 되돌리기 한 단계로 묶는다.
  const eraseDragRef = useRef(/** @type {null | { id: number, joinPrev: boolean, removed: boolean }} */ (null));
  function commitErase(index, path, radius, meta) {
    let drag = eraseDragRef.current;
    if (!drag || drag.id !== meta.dragId) {
      drag = { id: meta.dragId, joinPrev: meta.startedAt - lastInkAtRef.current < INK_GROUP_MS, removed: false };
      eraseDragRef.current = drag;
    }
    lastInkAtRef.current = meta.endedAt;
    const job = inkQueueRef.current
      .then(async () => {
        const result = await api('pdf.inkErase', {
          pageIndex: index,
          path,
          radius,
          continueGroup: drag.removed || drag.joinPrev,
        });
        if (result.removed > 0) {
          drag.removed = true;
          await refreshInkPage(result.doc, index);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : '지우지 못했습니다.');
      });
    inkQueueRef.current = job;
    return job;
  }

  async function startDrawing() {
    if (!docRef.current.open) return;
    setError('');
    await imageEditRef.current?.commit();
    setDrawOn(true);
  }

  // 이미지 넣기: 클립보드/파일의 이미지를 현재 쪽에 올려 놓고 위치·크기를 고르게 한다. Enter·바깥 클릭으로 확정.
  function placeImage(fromClipboard) {
    return imageEdit.place({ fromClipboard: Boolean(fromClipboard) });
  }

  // 이미지 파일을 쪽 위로 끌어다 놓으면 놓은 자리에 올려 둔다(좌측 썸네일 창에 놓으면 기존처럼 병합).
  function dragHasImage(event) {
    return Array.from(event.dataTransfer?.items || []).some((entry) => entry.kind === 'file' && entry.type.startsWith('image/'));
  }

  function onViewerDragOver(event) {
    if (!docRef.current.open || !dragHasImage(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }

  async function onViewerDrop(event) {
    const file = Array.from(event.dataTransfer?.files || []).find((entry) => entry.type.startsWith('image/'));
    if (!file || !docRef.current.open) return;
    event.preventDefault();
    event.stopPropagation();
    const target = event.target instanceof Element ? event.target.closest('[data-page]') : null;
    const index = target ? Number(target.getAttribute('data-page')) : pageIndexRef.current;
    let centerAt;
    if (target) {
      const box = target.getBoundingClientRect();
      const [ptW, ptH] = pageSizes[index] ?? FALLBACK_PAGE_PT;
      centerAt = {
        x: ((event.clientX - box.left) / Math.max(1, box.width)) * ptW,
        y: ((event.clientY - box.top) / Math.max(1, box.height)) * ptH,
      };
    }
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      await imageEdit.place({ image: btoa(binary), pageIndex: index, centerAt });
    } catch (err) {
      setError(err instanceof Error ? err.message : '이미지를 넣지 못했습니다.');
    }
  }

  async function endDrawing() {
    await flushInk();
    setDrawOn(false);
  }

  function toggleDrawing() {
    if (drawOnRef.current) void endDrawing();
    else void startDrawing();
  }

  useEffect(
    () => () => {
      for (const timer of Object.values(thumbTimersRef.current)) window.clearTimeout(timer);
    },
    [],
  );

  // 인쇄 대화상자를 연다. 그리던 것·편집 중인 이미지를 먼저 반영해야 인쇄물에 들어간다.
  async function openPrint(indices) {
    if (!doc.pageCount) return;
    setError('');
    try {
      await flushInk();
      setPrintScope({ indices: Array.isArray(indices) && indices.length ? indices : null });
    } catch (err) {
      setError(err instanceof Error ? err.message : '인쇄를 준비하지 못했습니다.');
    }
  }

  function printDoc() {
    return openPrint(null);
  }

  async function manageAssoc() {
    try {
      const statusInfo = await api('pdf.assocStatus');
      if (!statusInfo.windows) {
        void dialog.alert({ title: 'PDF 파일 연결', body: 'Windows에서만 사용할 수 있습니다.' });
        return;
      }
      const statusLine = statusInfo.registered ? '등록됨' : '등록 안 됨';
      const choice = await dialog.choose({
        title: 'PDF 파일 연결',
        body:
          `현재 상태: ${statusLine}\n\n` +
          '「연결」: Windows 연결 프로그램 목록에 Tiny PDF Editor - NEO를 추가합니다.\n' +
          '「연결 해제」: 이 프로그램으로 등록한 항목을 삭제합니다.\n' +
          '「기본 앱 설정 열기」: Windows에서 PDF를 여는 기본 프로그램을 고릅니다.\n\n' +
          '연결만으로는 기본 앱이 바뀌지 않습니다.\n' +
          'PDF를 더블클릭해 이 프로그램으로 열려면, Windows 설정에서\n' +
          '기본 앱을 「Tiny PDF Editor - NEO」로 선택하세요.',
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
      const statusLine = statusInfo.installed ? '설치됨' : '설치 안 됨';
      const choice = await dialog.choose({
        title: '가상 프린터',
        body:
          `현재 상태: ${statusLine}\n\n` +
          '다른 프로그램의 인쇄 창에서 「Tiny PDF Editor」를 고르면\n' +
          'PDF가 다운로드 폴더에 저장된 뒤 이 프로그램에서 열립니다.\n' +
          '앱이 꺼져 있어도 인쇄하면 자동으로 열립니다.\n' +
          'Windows 기본 「Microsoft Print to PDF」 드라이버를 사용합니다.',
        primaryLabel: statusInfo.installed ? '제거' : '설치',
        cancelLabel: '닫기',
      });
      if (choice !== 'primary') return;
      if (statusInfo.installed) await api('pdf.printerUninstall');
      else await api('pdf.printerInstall');
      void dialog.alert({
        title: '가상 프린터',
        body: statusInfo.installed
          ? '가상 프린터를 제거했습니다.'
          : '프린터 목록에 「Tiny PDF Editor」가 추가되었습니다.\n' +
            '인쇄하면 PDF가 다운로드 폴더에 저장되고 이 프로그램에서 열립니다.\n' +
            '앱이 꺼져 있어도 동작합니다.',
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '가상 프린터를 처리하지 못했습니다.');
    }
  }

  useEffect(() => {
    // 단축키는 활성 탭에서만 처리한다 (숨은 탭이 같은 키를 받지 않게).
    if (!active) return undefined;
    const onKeyDown = (event) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      // F11·Esc 는 AppMenuBar / 브라우저 전체화면이 처리한다. 여기서 따로 다루지 않는다.
      if (event.key === 'ArrowLeft') void goTo(pageIndex - (facing ? 2 : 1));
      if (event.key === 'ArrowRight') void goTo(pageIndex + (facing ? 2 : 1));
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [fullscreen, facing, pageIndex, active]);

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

  // 창 닫기(X)·종료 요청이 오면 저장 여부를 묻고, 진행해도 되는지 메인 프로세스에 답한다.
  // 최신 doc 상태를 읽도록 ref 로 호출한다. (브리지는 window.frame 이다. Electron 밖에서는 없다.)
  const confirmCloseRef = useRef(null);
  confirmCloseRef.current = () =>
    confirmUnsavedChanges({
      title: '저장 여부',
      body: `'${docRef.current.name}'의 변경 사항을 저장하시겠습니까?`,
      extraLabel: '저장하지 않고 닫기',
    });
  // 창 닫기 요청은 DocumentTabs 가 모든 탭을 차례로 확인한 뒤 처리한다. 여기서는 이 탭의 확인 함수만 등록한다.
  const closeDocRef = useRef(null);
  closeDocRef.current = closeDoc;
  // 앱 밖에서 넘어온 파일도 메뉴의 '열기'와 같은 라우팅(빈 문서면 여기, 아니면 새 창/새 탭)을 탄다.
  const openFileTargetRef = useRef(null);
  openFileTargetRef.current = openFileTarget;
  useEffect(() => {
    if (!onRegisterControls) return undefined;
    onRegisterControls(tabKey, {
      confirmClose: () => confirmCloseRef.current(),
      closeDoc: () => closeDocRef.current?.(),
      openPath: (filePath) => openFileTargetRef.current?.(filePath),
    });
    return () => onRegisterControls(tabKey, null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabKey, onRegisterControls]);

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
      convert: () => void convertFiles(),
      save: () => void save(),
      saveAs: () => void saveAs(),
      close: () => void closeDoc(),
      exportImages: () => setExportScope({ indices: null }),
      print: () => void printDoc(),
      assoc: () => void manageAssoc(),
      printer: () => void managePrinter(),
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
      reduce: () => {
        setReduceSourceDpi(null);
        setReduceOpen(true);
        // 창은 바로 열고, 문서 그림의 원본 해상도는 알아내는 대로 채운다(실패해도 창에는 영향 없음).
        api('pdf.imageDpi')
          .then((info) => setReduceSourceDpi(Number(info?.dpi) > 0 ? Number(info.dpi) : null))
          .catch(() => setReduceSourceDpi(null));
      },
      pageNumber: () => setPageNumberOpen(true),
      ocr: () => setOcrScope({ indices: null }),
      draw: () => toggleDrawing(),
      getDraw: () => drawOnRef.current,
      imgClip: () => void placeImage(true),
      imgFile: () => void placeImage(false),
      setPw: () => void setDocPassword(),
      clearPw: () => void clearPassword(),
      pii: () => void removePii(),
      fitWidth: () => fit('width'),
      fitHeight: () => fit('height'),
      fitPage: () => fit('page'),
      facing: () => applyFacing(!facing),
      getFacing: () => facing,
    },
    { ready: engineReady, docOpen: doc.open },
    active,
  );

  // 탭 묶음(DocumentTabs)에 이 탭의 문서 상태를 알린다. 탭 바와 종료 확인에 쓴다.
  useEffect(() => {
    onDocChange?.(tabKey, {
      name: doc.path ? doc.name : '빈 문서(noname)',
      open: Boolean(doc.open),
      modified: Boolean(doc.modified),
    });
  }, [onDocChange, tabKey, doc.open, doc.name, doc.path, doc.modified]);

  // 하단 단추가 접히기 직전에서 창 줄이기가 멈추도록 창 최소 너비를 알린다. 값은 항상 같다(왼쪽 칸 고정 + 단추 줄).
  useEffect(() => {
    if (!active || fullscreen) return;
    window.frame?.setMinContentWidth?.(MIN_CONTENT_WIDTH);
  }, [active, fullscreen]);

  // 활성 탭의 쪽 보기 방식을 메뉴(보기 > 두 쪽씩 보기)에 알린다.
  useEffect(() => {
    if (!active) return;
    window.dispatchEvent(new CustomEvent('tiny:facing', { detail: facing }));
  }, [facing, active]);

  // 한쪽씩/두쪽씩 보기 전환. 하단 토글·메뉴·Ctrl+2 가 모두 이 함수를 쓴다.
  // 이미 그린 쪽 그림은 그대로 쓰고(다시 그리지 않음), 보던 쪽이 화면에서 같은 자리에 오도록 스크롤만 맞춘다.
  // 모자란 쪽은 위의 근처 쪽 채우기 effect 가 조용히 채운다.
  const facingAnchorRef = useRef(null);
  function applyFacing(next) {
    if (next === facing) return;
    const view = viewRef.current;
    const target = next ? pageIndex - (pageIndex % 2) : pageIndex;
    const el = view?.querySelector(`[data-page="${target}"]`);
    facingAnchorRef.current = view && el
      ? { index: target, offset: el.getBoundingClientRect().top - view.getBoundingClientRect().top }
      : { index: target, offset: null };
    setFacing(next);
    if (target !== pageIndex) setPageIndex(target);
  }
  useLayoutEffect(() => {
    const anchor = facingAnchorRef.current;
    if (!anchor) return;
    facingAnchorRef.current = null;
    const view = viewRef.current;
    const el = view?.querySelector(`[data-page="${anchor.index}"]`);
    if (!view || !el) return;
    if (anchor.offset == null) {
      scrollToPage(anchor.index);
      return;
    }
    const now = el.getBoundingClientRect().top - view.getBoundingClientRect().top;
    view.scrollTop += now - anchor.offset;
  }, [facing]);

  const zoomPercent = Math.round(zoom * 100);
  const canNav = doc.open && doc.pageCount > 0;
  // 이전·다음 단추의 이동 폭: 두쪽씩 보기는 한 번에 한 쌍(2쪽)씩, 한쪽씩 보기는 1쪽씩.
  const pageStep = facing ? 2 : 1;
  // 한쪽씩 보기는 행마다 쪽 1개, 두쪽씩 보기는 쪽 2개.
  const pageRows = [];
  if (canNav) {
    const step = facing ? 2 : 1;
    for (let start = 0; start < doc.pageCount; start += step) {
      pageRows.push(Array.from({ length: Math.min(step, doc.pageCount - start) }, (_, k) => start + k));
    }
  }
  // 파일 추가 중에는 들어올 자리에 아직 안 온 파일 수만큼 빈 카드를 보여 준다.
  const pendingInsert =
    progress?.op === 'insert' && progress.total > 0
      ? { at: progress.at, count: Math.max(0, progress.total - progress.current) }
      : null;
  const statusHint = busy
    ? busy
    : doc.open
      ? `${doc.name}${doc.modified ? ' · 수정됨' : ''}`
      : '';

  return (
    <div className="flex h-full min-h-0 flex-col bg-app-surface">
      {!fullscreen && (
        <>
          {status && !engineReady ? (
            <p className="border-b border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
              {status.error || 'PDF 엔진을 시작하지 못했습니다.'}
            </p>
          ) : null}
        </>
      )}

      <div className="relative flex min-h-0 flex-1">
        {(!fullscreen || fullscreenPanelOpen) && <PageSide
          docOpen={doc.open}
          pageIndex={pageIndex}
          pageCount={doc.pageCount || 0}
          thumbs={thumbs}
          markups={markups}
          markupTabRequest={markupTabRequest}
          clipboardCount={clipboardCount}
          onSelectPage={(index) => void goTo(index)}
          onThumbAction={(action) => void handleThumbAction(action)}
          pendingInsert={pendingInsert}
          collapsed={panelCollapsed}
          onCollapsedChange={setPanelCollapsed}
        />
        }

        <div className="relative flex min-w-0 flex-1 flex-col">
          <PanelToggleTab
            collapsed={fullscreen ? !fullscreenPanelOpen : panelCollapsed}
            onToggle={() =>
              fullscreen
                ? setFullscreenPanelOpen((value) => !value)
                : setPanelCollapsed((value) => !value)
            }
          />
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
          {drawOn && doc.open ? (
            <DrawToolbar state={drawState} onChange={setDrawState} onDone={() => void endDrawing()} shapeEdit={shapeEdit} />
          ) : null}
          {imageEdit.active && doc.open && !drawOn ? (
            <ImageToolbar controller={imageEdit} pageCount={doc.pageCount} confirm={dialog.confirm} />
          ) : null}
          <main
            ref={viewRef}
            className="min-h-0 flex-1 overflow-auto"
            onScroll={onViewerScroll}
            onDragOver={onViewerDragOver}
            onDrop={(event) => void onViewerDrop(event)}
          >
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
                              enabled={doc.open && !busy && !drawOn && !imageEdit.active}
                              onMarkupChanged={(nextDoc) => void refreshAfterMarkup(nextDoc)}
                              onNotice={notifyMarkup}
                            />
                          ) : null}
                          {src ? (
                            <ImageLayer
                              pageIndex={index}
                              ptW={ptW}
                              ptH={ptH}
                              controller={imageEdit}
                              showHits={doc.open && !busy && !drawOn}
                            />
                          ) : null}
                          {shapeToolOn && src && !imageEdit.active ? (
                            <ShapeLayer
                              pageIndex={index}
                              ptW={ptW}
                              ptH={ptH}
                              tool={drawState.tool}
                              newParams={newShapeParams}
                              controller={shapeEdit}
                            />
                          ) : null}
                          {drawOn && !shapeToolOn && src && !imageEdit.active ? (
                            <DrawLayer
                              pageIndex={index}
                              ptW={ptW}
                              ptH={ptH}
                              tool={drawState.tool}
                              settings={
                                drawState.tool === 'eraser'
                                  ? { radius: drawState.eraserRadius }
                                  : (drawState.tools[drawState.tool] ?? drawState.tools.pen)
                              }
                              onStroke={commitInk}
                              onErase={commitErase}
                            />
                          ) : null}
                          {src && searchOpen && searchHits[searchIndex]?.pageIndex === index ? (
                            <div
                              data-search-hit
                              className="pointer-events-none absolute rounded-sm border border-orange-400 bg-yellow-300/40"
                              style={{
                                left: `${(searchHits[searchIndex].x0 / ptW) * 100}%`,
                                top: `${(searchHits[searchIndex].y0 / ptH) * 100}%`,
                                width: `${((searchHits[searchIndex].x1 - searchHits[searchIndex].x0) / ptW) * 100}%`,
                                height: `${((searchHits[searchIndex].y1 - searchHits[searchIndex].y0) / ptH) * 100}%`,
                              }}
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
                  <h1 className="m-0 text-lg font-semibold text-slate-800">빈 문서</h1>
                  <p className="mt-2 text-sm leading-relaxed text-slate-500">
                    병합할 PDF, 이미지나 한글(HWP, HWPX) 파일을
                    <br />
                    좌측 썸네일 창으로 드래그 앤 드롭 해주세요
                  </p>
                  {busy ? <p className="mt-3 text-sm text-slate-500">{busy}</p> : null}
                </div>
              </div>
            )}
          </main>

          {/* 진행 안내(z-40) 위로 올려서, 작업 중에도 [세부진행상황 보기] 로 연 터미널을 읽고 접을 수 있게 한다. */}
          <div className="relative z-50">
            <TerminalPanel
              open={terminal.open}
              expanded={terminal.expanded}
              lines={terminal.lines}
              onToggleExpanded={() => setTerminal((prev) => ({ ...prev, expanded: !prev.expanded }))}
              onClose={() => setTerminal((prev) => ({ ...prev, open: false }))}
            />
          </div>

          {progress?.blocking ? (
            <div
              data-progress-card="1"
              className="absolute inset-0 z-40 flex cursor-progress items-center justify-center bg-white/70"
            >
              <div className="w-[320px] max-w-[90%] rounded-lg border border-app-border bg-white px-5 py-4 text-center shadow-lg">
                <div className="text-sm font-medium text-slate-800">
                  {progress.cancelling ? `${progress.title} - 취소하는 중...` : progress.title}
                </div>
                <div className="mt-1 flex h-4 items-center justify-center gap-2 text-xs text-slate-500">
                  <span className="shrink-0">{progressDetail(progress).count}</span>
                  <span className="min-w-0 truncate" title={progressDetail(progress).name}>
                    {progressDetail(progress).name}
                  </span>
                </div>
                <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                  <div
                    data-progress-bar="1"
                    className={`h-full bg-app-accent transition-[width] duration-200 ${progress.total ? '' : 'animate-pulse'}`}
                    style={{ width: progress.total ? `${Math.min(100, Math.round((progress.current / progress.total) * 100))}%` : '30%' }}
                  />
                </div>
                <div className="mt-3 flex items-center justify-center gap-2">
                  <button
                    type="button"
                    data-progress-cancel="1"
                    className="h-7 rounded border border-slate-300 bg-white px-3 text-xs text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                    disabled={progress.cancelling}
                    onClick={cancelProgress}
                  >
                    취소
                  </button>
                  <button
                    type="button"
                    className="h-7 rounded px-2 text-xs text-slate-500 hover:bg-slate-100"
                    onClick={() => setTerminal((prev) => ({ ...prev, open: true }))}
                  >
                    세부진행상황 보기
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
        {/* 작업이 도는 동안 좌측 썸네일·본문 어디도 클릭되지 않게 막는다 (흐림과 안내는 본문 영역에서 보여 준다). */}
        {progress?.blocking ? (
          <div data-progress-block="1" className="absolute inset-0 z-30 cursor-progress" aria-hidden="true" />
        ) : null}
      </div>

      {/* 하단 막대는 창 전체 너비를 쓴다. 왼쪽 칸은 (왼쪽 탭 + 썸네일 패널) 너비로 고정해 두고 문서 이름·진행 상태를 한 줄로 보여 주며,
          넘치면 … 로 줄인다. 패널을 접고 펴도 칸 너비가 같아서, 오른쪽 단추들은 움직이지 않고 항상 남은 너비의 가운데에 있다. */}
      <footer className="flex h-9 shrink-0 items-center border-t border-app-border bg-[#f7f7f7]">
        <div className="flex h-full shrink-0 items-center px-2" style={{ width: SIDE_FOOTER_WIDTH }}>
          <span
            className="block min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[11px] text-slate-500"
            title={statusHint}
            data-status-hint="1"
          >
            {statusHint}
          </span>
        </div>
        <div className="flex h-full min-w-0 flex-1 items-center justify-center px-2">
          <div className="flex shrink-0 items-center gap-1 whitespace-nowrap" data-footer-controls="1">
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
              onClick={() => void goTo(pageIndex - pageStep)}
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
              className="h-[22px] w-16 shrink-0 rounded border border-slate-300 bg-white px-1 text-center text-[12px] text-slate-700 outline-none focus:border-app-accent disabled:opacity-50"
            />
            <span className="px-0.5 text-[12px] text-slate-600">/ {doc.open ? doc.pageCount : 0}</span>
            <button
              type="button"
              className={barBtnClass}
              title="다음 페이지"
              disabled={!canNav || pageIndex + pageStep >= doc.pageCount}
              onClick={() => void goTo(pageIndex + pageStep)}
            >
              <NavIcon kind="next" />
            </button>
            <button
              type="button"
              className={barBtnClass}
              title="마지막 페이지"
              disabled={!canNav || pageIndex + pageStep >= doc.pageCount}
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

            <div role="group" aria-label="쪽 보기 방식" className="ml-1 inline-flex shrink-0 overflow-hidden rounded border border-slate-300">
              {[
                { value: false, label: '1쪽', title: '한 쪽씩 보기' },
                { value: true, label: '2쪽', title: '두 쪽씩 보기 (Ctrl+2)' },
              ].map((mode) => (
                <button
                  key={mode.label}
                  type="button"
                  title={mode.title}
                  aria-pressed={facing === mode.value}
                  data-facing-toggle={mode.value ? 'two' : 'one'}
                  disabled={!doc.open}
                  onClick={() => applyFacing(mode.value)}
                  className={`inline-flex h-[20px] w-9 items-center justify-center text-[11px] font-medium disabled:opacity-40 ${
                    facing === mode.value ? 'bg-app-accent text-white' : 'bg-white text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  {mode.label}
                </button>
              ))}
            </div>

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
              className="h-[22px] w-[88px] shrink-0 disabled:opacity-40"
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
              className="h-[22px] w-[76px] shrink-0 rounded border border-slate-300 bg-white px-1 text-center text-[12px] text-slate-700 outline-none focus:border-app-accent disabled:opacity-50"
            />
            <datalist id="editor-zoom-presets">
              {ZOOM_PRESETS.map((value) => (
                <option key={value} value={`${value}%`} />
              ))}
            </datalist>
            <button
              type="button"
              className={barBtnClass}
              title="전체 화면 (F11)"
              aria-label="전체 화면"
              data-fullscreen-enter="1"
              onClick={enterFullscreen}
            >
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M2.5 6V2.5H6" />
                <path d="M10 2.5h3.5V6" />
                <path d="M13.5 10v3.5H10" />
                <path d="M6 13.5H2.5V10" />
              </svg>
            </button>
          </div>
        </div>
      </footer>

      <PdfConvertDialog
        open={convertOpen}
        onClose={() => setConvertOpen(false)}
        onDone={(openPath) => {
          setConvertOpen(false);
          if (openPath) void openFileTarget(openPath);
        }}
      />
      <ReduceSizeDialog
        open={reduceOpen}
        sourceDpi={reduceSourceDpi}
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
      <PrintDialog
        open={Boolean(printScope)}
        api={api}
        pageCount={doc.pageCount || 0}
        pageIndex={pageIndex}
        pageSizes={pageSizes}
        indices={printScope?.indices ?? null}
        onClose={() => setPrintScope(null)}
        onPrinted={({ sheets }) => {
          setPrintScope(null);
          setToast({ message: `인쇄 작업을 프린터로 보냈습니다. (${sheets}장)`, type: 'success' });
        }}
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
        fileName={passwordPath ? passwordPath.split(/[\\/]/).pop() : ''}
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

      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
          autoClose={5000}
        />
      )}
    </div>
  );
}
