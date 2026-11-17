import { useEffect, useMemo, useRef, useState } from 'react';
import {
  DEFAULT_PRINT_OPTIONS,
  PAPER_SIZES,
  PER_SHEET_CHOICES,
  layoutSheets,
  marginMmOf,
  normalizePrintOptions,
  parsePageRange,
} from '../../../shared/printLayout.js';

/**
 * 인쇄 대화상자: 왼쪽 설정, 오른쪽 미리보기 (Chrome 인쇄 창과 같은 구성).
 * 미리보기와 실제 인쇄는 같은 배치 계산(shared/printLayout.js)을 쓰므로 보이는 그대로 인쇄된다.
 *
 * - indices: null 이면 문서 전체, 배열이면 썸네일에서 고른 쪽 (0 기반).
 * - 설정은 다음에 열 때도 기억한다 (프린터 이름 포함).
 */

const STORAGE_KEY = 'tinypdfneo.printOptions';
const PREVIEW_ZOOM = 1.2;

const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'flex max-h-full w-full max-w-[920px] flex-col rounded-xl bg-white shadow-xl';
const labelClass = 'text-sm font-medium text-slate-700';
const fieldClass =
  'h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-800 outline-none focus:border-app-accent disabled:opacity-50';
const btnBase =
  'inline-flex h-9 min-w-[88px] items-center justify-center rounded-full px-4 text-sm font-medium transition-colors disabled:cursor-default disabled:opacity-50';
const btnPrimary = `${btnBase} bg-app-accent text-white hover:bg-app-accentHover disabled:hover:bg-app-accent`;
const btnGhost = `${btnBase} border border-slate-300 text-slate-700 hover:bg-slate-100`;

function loadSaved() {
  try {
    return normalizePrintOptions(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null'));
  } catch {
    return { ...DEFAULT_PRINT_OPTIONS };
  }
}

function saveOptions(options) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(options));
  } catch {
    /* 저장하지 못해도 인쇄에는 영향이 없다 */
  }
}

/** 입력 중에는 글자를 그대로 두고, 범위 안의 숫자일 때만 값을 올린다. 포커스를 잃으면 범위로 맞춘다. */
function NumField({ value, min, max, onCommit, className, ...rest }) {
  const [text, setText] = useState(String(value));
  useEffect(() => {
    setText((prev) => (Number(prev) === value ? prev : String(value)));
  }, [value]);
  return (
    <input
      {...rest}
      type="number"
      min={min}
      max={max}
      className={className}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        const n = Number(event.target.value);
        if (event.target.value !== '' && Number.isFinite(n) && n >= min && n <= max) onCommit(n);
      }}
      onBlur={() => {
        const n = Number(text);
        const next = text === '' || !Number.isFinite(n) ? value : Math.min(max, Math.max(min, n));
        setText(String(next));
        onCommit(next);
      }}
    />
  );
}

function Row({ label, children }) {
  return (
    <div className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
    </div>
  );
}

/**
 * @param {{
 *   open: boolean,
 *   api: (name: string, body?: unknown) => Promise<any>,
 *   pageCount: number,
 *   pageIndex: number,
 *   pageSizes: number[][],
 *   indices: number[] | null,
 *   onClose: () => void,
 *   onPrinted: (result: { sheets: number, pages: number }) => void,
 * }} props
 */
export default function PrintDialog({ open, api, pageCount, pageIndex, pageSizes, indices, onClose, onPrinted }) {
  const [options, setOptions] = useState(() => loadSaved());
  const [printers, setPrinters] = useState(/** @type {{ name: string, displayName: string, isDefault: boolean }[]} */ ([]));
  const [printersLoaded, setPrintersLoaded] = useState(false);
  const [rangeMode, setRangeMode] = useState('all');
  const [rangeText, setRangeText] = useState('');
  const [sheetNo, setSheetNo] = useState(0);
  const [previews, setPreviews] = useState(/** @type {Record<number, string>} */ ({}));
  const [printing, setPrinting] = useState(false);
  const [error, setError] = useState('');
  const apiRef = useRef(api);
  apiRef.current = api;
  const previewCache = useRef(/** @type {Map<number, string>} */ (new Map()));
  const previewAreaRef = useRef(/** @type {HTMLDivElement | null} */ (null));
  const [box, setBox] = useState({ w: 400, h: 480 });

  // 미리보기 칸 크기에 맞춰 용지 그림 크기를 정한다 (창이 작아도 잘리지 않게).
  useEffect(() => {
    if (!open) return undefined;
    const el = previewAreaRef.current;
    if (!el) return undefined;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) setBox({ w: rect.width, h: rect.height });
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [open]);
  const selection = Array.isArray(indices) && indices.length ? indices : null;

  // 열 때마다 처음 상태로: 범위·미리보기를 비우고 프린터 목록을 새로 읽는다.
  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    previewCache.current = new Map();
    setPreviews({});
    setSheetNo(0);
    setError('');
    setPrinting(false);
    setRangeMode(selection ? 'selection' : 'all');
    setRangeText('');
    setPrintersLoaded(false);
    apiRef.current('pdf.printers')
      .then((result) => {
        if (cancelled) return;
        const list = Array.isArray(result?.printers) ? result.printers : [];
        setPrinters(list);
        setOptions((prev) => {
          if (prev.printer && list.some((p) => p.name === prev.printer)) return prev;
          const fallback = list.find((p) => p.isDefault) ?? list[0];
          return { ...prev, printer: fallback ? fallback.name : '' };
        });
      })
      .catch(() => {
        if (!cancelled) setPrinters([]);
      })
      .finally(() => {
        if (!cancelled) setPrintersLoaded(true);
      });
    return () => {
      cancelled = true;
    };
    // selection 은 열린 순간의 값만 쓴다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const range = useMemo(() => {
    if (rangeMode === 'selection' && selection) return { indices: selection.filter((i) => i < pageCount), error: '' };
    if (rangeMode === 'current') {
      return { indices: pageCount > 0 ? [Math.min(Math.max(pageIndex, 0), pageCount - 1)] : [], error: '' };
    }
    if (rangeMode === 'custom') return parsePageRange(rangeText, pageCount);
    return { indices: Array.from({ length: pageCount }, (_, i) => i), error: '' };
  }, [rangeMode, rangeText, selection, pageIndex, pageCount]);

  const layout = useMemo(
    () => layoutSheets(range.indices.map((i) => pageSizes[i] ?? [595.28, 841.89]), options),
    [range.indices, pageSizes, options],
  );
  const sheetCount = layout.sheets.length;
  const safeSheetNo = Math.min(sheetNo, Math.max(0, sheetCount - 1));
  const sheet = layout.sheets[safeSheetNo];

  useEffect(() => {
    if (sheetNo !== safeSheetNo) setSheetNo(safeSheetNo);
  }, [sheetNo, safeSheetNo]);

  // 지금 보이는 장에 필요한 쪽만 그린다 (한 번 그린 쪽은 다시 그리지 않는다).
  useEffect(() => {
    if (!open || !sheet) return undefined;
    let cancelled = false;
    const wanted = sheet.cells.map((c) => range.indices[c.i]).filter((i) => !previewCache.current.has(i));
    (async () => {
      for (const index of wanted) {
        if (cancelled) return;
        try {
          const image = await apiRef.current('pdf.render', { index, zoom: PREVIEW_ZOOM });
          if (cancelled) return;
          previewCache.current.set(index, `data:image/png;base64,${image.png}`);
          setPreviews((prev) => ({ ...prev, [index]: previewCache.current.get(index) }));
        } catch {
          /* 이 쪽은 빈 칸으로 둔다 */
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, sheet, range.indices]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape' && !printing) {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [open, printing, onClose]);

  if (!open) return null;

  const set = (patch) => setOptions((prev) => normalizePrintOptions({ ...prev, ...patch }));
  const [sheetW, sheetH] = layout.sheetMm;
  const pxPerMm = Math.max(0.2, Math.min((box.w - 8) / sheetW, (box.h - 8) / sheetH));
  const noPrinter = !options.systemDialog && !options.printer;
  const canPrint = !printing && !range.error && range.indices.length > 0 && !noPrinter;
  const firstScale = sheet?.cells[0]?.scale;
  const scaleNote =
    sheet && sheet.cells.length === 1 && Number.isFinite(firstScale)
      ? ` · 배율 ${Math.round(firstScale * 100)}%`
      : '';

  async function submit() {
    if (!canPrint) return;
    setError('');
    setPrinting(true);
    saveOptions(options);
    try {
      const result = await api('pdf.printRun', { options, indices: range.indices });
      if (result?.canceled) {
        setPrinting(false);
        return;
      }
      setPrinting(false);
      onPrinted({ sheets: result?.sheets ?? sheetCount, pages: result?.pages ?? range.indices.length });
    } catch (err) {
      setPrinting(false);
      setError(err instanceof Error ? err.message : '인쇄하지 못했습니다.');
    }
  }

  const pagesLabel = range.indices.length ? `${range.indices.length}쪽` : '0쪽';

  return (
    <div className={overlayClass} role="presentation">
      <div role="dialog" aria-modal="true" aria-labelledby="print-title" className={cardClass} data-print-dialog>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 id="print-title" className="m-0 text-base font-semibold text-slate-900">
            인쇄
          </h2>
          <span className="text-sm text-slate-500">
            {pagesLabel} · {sheetCount}장
            {options.copies > 1 ? ` × ${options.copies}부` : ''}
          </span>
        </div>

        <div className="flex min-h-0 gap-0" style={{ height: 'min(600px, calc(100vh - 160px))' }}>
          {/* 왼쪽: 설정 */}
          <div className="flex w-[330px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-slate-200 px-5 py-4">
            <Row label="프린터">
              <select
                className={fieldClass}
                value={options.printer}
                disabled={options.systemDialog || printing}
                data-print="printer"
                onChange={(e) => set({ printer: e.target.value })}
              >
                {!printers.length ? (
                  <option value="">{printersLoaded ? '사용할 수 있는 프린터가 없습니다' : '프린터를 찾는 중…'}</option>
                ) : null}
                {printers.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.displayName}
                    {p.isDefault ? ' (기본)' : ''}
                  </option>
                ))}
              </select>
            </Row>

            <Row label="인쇄할 쪽">
              <div className="flex flex-col gap-1.5 text-sm text-slate-700">
                <label className="flex items-center gap-2">
                  <input type="radio" name="print-range" checked={rangeMode === 'all'} onChange={() => setRangeMode('all')} />
                  모든 쪽 ({pageCount})
                </label>
                <label className="flex items-center gap-2">
                  <input type="radio" name="print-range" checked={rangeMode === 'current'} onChange={() => setRangeMode('current')} />
                  현재 쪽 ({pageIndex + 1})
                </label>
                {selection ? (
                  <label className="flex items-center gap-2">
                    <input type="radio" name="print-range" checked={rangeMode === 'selection'} onChange={() => setRangeMode('selection')} />
                    선택한 쪽 ({selection.length})
                  </label>
                ) : null}
                <label className="flex items-center gap-2">
                  <input type="radio" name="print-range" checked={rangeMode === 'custom'} onChange={() => setRangeMode('custom')} />
                  범위
                  <input
                    className={`${fieldClass} flex-1`}
                    value={rangeText}
                    placeholder="예: 1-3, 5"
                    data-print="range"
                    onFocus={() => setRangeMode('custom')}
                    onChange={(e) => {
                      setRangeMode('custom');
                      setRangeText(e.target.value);
                    }}
                  />
                </label>
                {range.error && rangeMode === 'custom' ? <span className="text-xs text-red-600">{range.error}</span> : null}
              </div>
            </Row>

            <div className="grid grid-cols-2 gap-3">
              <Row label="매수">
                <NumField
                  min={1}
                  max={99}
                  className={fieldClass}
                  value={options.copies}
                  data-print="copies"
                  onCommit={(copies) => set({ copies })}
                />
              </Row>
              <Row label="색상">
                <select className={fieldClass} value={options.color ? 'color' : 'gray'} data-print="color" onChange={(e) => set({ color: e.target.value === 'color' })}>
                  <option value="color">컬러</option>
                  <option value="gray">흑백</option>
                </select>
              </Row>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={options.collate} disabled={options.copies < 2} onChange={(e) => set({ collate: e.target.checked })} />
              한 부씩 인쇄
            </label>

            <Row label="양면">
              <select className={fieldClass} value={options.duplex} data-print="duplex" onChange={(e) => set({ duplex: e.target.value })}>
                <option value="simplex">한 면</option>
                <option value="longEdge">양면 (긴 쪽으로 넘김)</option>
                <option value="shortEdge">양면 (짧은 쪽으로 넘김)</option>
              </select>
            </Row>

            <div className="grid grid-cols-2 gap-3">
              <Row label="용지">
                <select className={fieldClass} value={options.paper} data-print="paper" onChange={(e) => set({ paper: e.target.value })}>
                  <option value="auto">자동 ({layout.paperId})</option>
                  {PAPER_SIZES.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </Row>
              <Row label="방향">
                <select className={fieldClass} value={options.orientation} data-print="orientation" onChange={(e) => set({ orientation: e.target.value })}>
                  <option value="auto">자동</option>
                  <option value="portrait">세로</option>
                  <option value="landscape">가로</option>
                </select>
              </Row>
            </div>

            <Row label="한 장에 모을 쪽 수">
              <select className={fieldClass} value={options.perSheet} data-print="perSheet" onChange={(e) => set({ perSheet: e.target.value })}>
                {PER_SHEET_CHOICES.map((n) => (
                  <option key={n} value={n}>
                    {n === 1 ? '1쪽 (모으지 않음)' : `${n}쪽`}
                  </option>
                ))}
              </select>
            </Row>

            <Row label="크기">
              <div className="flex gap-2">
                <select
                  className={fieldClass}
                  value={options.scale}
                  disabled={options.perSheet > 1}
                  data-print="scale"
                  onChange={(e) => set({ scale: e.target.value })}
                >
                  <option value="fit">용지에 맞춤</option>
                  <option value="shrink">큰 쪽만 줄임</option>
                  <option value="actual">실제 크기 (100%)</option>
                  <option value="custom">사용자 지정</option>
                </select>
                {options.scale === 'custom' && options.perSheet === 1 ? (
                  <span className="flex items-center gap-1">
                    <NumField
                      min={10}
                      max={400}
                      className={`${fieldClass} w-20`}
                      value={options.scalePercent}
                      data-print="scalePercent"
                      onCommit={(scalePercent) => set({ scalePercent })}
                    />
                    <span className="text-sm text-slate-500">%</span>
                  </span>
                ) : null}
              </div>
            </Row>

            <Row label="여백">
              <div className="flex gap-2">
                <select className={fieldClass} value={options.margin} data-print="margin" onChange={(e) => set({ margin: e.target.value })}>
                  <option value="none">없음</option>
                  <option value="default">기본 (5 mm)</option>
                  <option value="custom">사용자 지정</option>
                </select>
                {options.margin === 'custom' ? (
                  <span className="flex items-center gap-1">
                    <NumField
                      min={0}
                      max={50}
                      className={`${fieldClass} w-20`}
                      value={options.marginMm}
                      data-print="marginMm"
                      onCommit={(marginMm) => set({ marginMm })}
                    />
                    <span className="text-sm text-slate-500">mm</span>
                  </span>
                ) : null}
              </div>
            </Row>

            <label className="flex items-start gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={options.systemDialog}
                data-print="systemDialog"
                onChange={(e) => set({ systemDialog: e.target.checked })}
              />
              <span>
                Windows 인쇄 창 열기
                <span className="block text-xs text-slate-500">프린터 속성(용지함, 인쇄 품질 등)을 직접 정할 때 사용합니다.</span>
              </span>
            </label>
          </div>

          {/* 오른쪽: 미리보기 */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col items-center gap-3 bg-[#e8eaed] px-4 py-4">
            <div className="flex items-center gap-3 text-sm text-slate-700">
              <button
                type="button"
                className="h-7 w-7 rounded-full border border-slate-300 bg-white disabled:opacity-40"
                disabled={safeSheetNo <= 0}
                aria-label="이전 장"
                data-print="prev"
                onClick={() => setSheetNo(safeSheetNo - 1)}
              >
                ‹
              </button>
              <span data-print="sheetLabel">
                {sheetCount ? safeSheetNo + 1 : 0} / {sheetCount}
              </span>
              <button
                type="button"
                className="h-7 w-7 rounded-full border border-slate-300 bg-white disabled:opacity-40"
                disabled={safeSheetNo >= sheetCount - 1}
                aria-label="다음 장"
                data-print="next"
                onClick={() => setSheetNo(safeSheetNo + 1)}
              >
                ›
              </button>
            </div>

            <div ref={previewAreaRef} className="flex min-h-0 w-full flex-1 items-center justify-center overflow-hidden">
              {sheet ? (
                <div
                  className="relative bg-white shadow-md"
                  data-print="sheet"
                  style={{ width: sheetW * pxPerMm, height: sheetH * pxPerMm }}
                >
                  {sheet.cells.map((c) => {
                    const pageNo = range.indices[c.i];
                    const url = previews[pageNo];
                    return (
                      <div
                        key={c.i}
                        className="absolute overflow-hidden"
                        style={{ left: c.cell.x * pxPerMm, top: c.cell.y * pxPerMm, width: c.cell.w * pxPerMm, height: c.cell.h * pxPerMm }}
                      >
                        {url ? (
                          <img
                            src={url}
                            alt={`${pageNo + 1}쪽`}
                            draggable={false}
                            className="absolute block max-w-none"
                            style={{
                              left: c.img.x * pxPerMm,
                              top: c.img.y * pxPerMm,
                              width: c.img.w * pxPerMm,
                              height: c.img.h * pxPerMm,
                              filter: options.color ? undefined : 'grayscale(1)',
                              transform: c.rotated ? 'rotate(90deg)' : undefined,
                              boxShadow: '0 0 0 1px rgba(0,0,0,0.08)',
                            }}
                          />
                        ) : (
                          <div
                            className="absolute flex items-center justify-center bg-slate-100 text-xs text-slate-400"
                            style={{
                              left: c.img.x * pxPerMm,
                              top: c.img.y * pxPerMm,
                              width: c.img.w * pxPerMm,
                              height: c.img.h * pxPerMm,
                              transform: c.rotated ? 'rotate(90deg)' : undefined,
                            }}
                          >
                            {pageNo + 1}쪽
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {marginMmOf(layout.options) > 0 ? (
                    <div
                      className="pointer-events-none absolute border border-dashed border-sky-300/70"
                      style={{
                        left: layout.marginMm * pxPerMm,
                        top: layout.marginMm * pxPerMm,
                        right: layout.marginMm * pxPerMm,
                        bottom: layout.marginMm * pxPerMm,
                      }}
                    />
                  ) : null}
                </div>
              ) : (
                <span className="text-sm text-slate-500">인쇄할 쪽이 없습니다.</span>
              )}
            </div>

            <span className="text-xs text-slate-600" data-print="info">
              {layout.paperId} · {layout.landscape ? '가로' : '세로'}
              {scaleNote}
            </span>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-slate-200 px-5 py-3">
          <span className="min-w-0 flex-1 truncate text-sm text-red-600" role="alert" data-print="error">
            {error || (noPrinter && printersLoaded ? '프린터를 선택해 주세요.' : '')}
          </span>
          <div className="flex gap-2">
            <button type="button" className={btnPrimary} disabled={!canPrint} data-print="submit" onClick={() => void submit()}>
              {printing ? '인쇄 중…' : '인쇄'}
            </button>
            <button type="button" className={btnGhost} disabled={printing} data-print="cancel" onClick={onClose}>
              취소
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
