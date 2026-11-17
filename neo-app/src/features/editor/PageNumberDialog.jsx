import { useEffect, useState } from 'react';

/**
 * 쪽 번호 매기기 대화상자 (Tiny page_number_dialog.py PageNumberDialog 를 옮긴 것).
 * - 왼쪽: 번호 위치 3×2 격자 + 쪽 미리보기 + 가로/세로 여백 + "쪽 번호 없음"
 * - 가운데: 번호 모양, 줄표, 접두사/접미사, 시작·끝 쪽, 시작 번호, 크기, 색상, 배경
 * - 열 때 이미 넣어 둔 쪽 번호 설정이 있으면 그 값으로 채운다 (원본 load_applied_page_number_options)
 *
 * 값 키(camelCase)는 pdf_editor/engine.py 의 _page_number_options 와 맞춘다.
 */

const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
// 가로 566px: 접두사·접미사 입력칸을 134px 로 줄인 만큼(730 → 566) 창도 좁힌다.
const cardClass = 'flex w-full max-w-[566px] flex-col rounded-xl bg-white p-5 shadow-xl';
const labelClass = 'whitespace-nowrap text-sm text-slate-700';
// 너비(w-*)는 호출부에서 따로 지정한다. fieldClass 에 w-full 을 넣어 두면 호출부 w-* 를 덮어쓴다.
const fieldBase =
  'h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-800 outline-none focus:border-app-accent disabled:opacity-50';
const fieldClass = `${fieldBase} w-full`;
const btnBase = 'inline-flex h-9 w-[88px] items-center justify-center rounded-full text-sm font-medium transition-colors disabled:cursor-default disabled:opacity-50';
const btnPrimary = `${btnBase} bg-app-accent text-white hover:bg-app-accentHover disabled:hover:bg-app-accent`;
const btnGhost = `${btnBase} border border-slate-300 text-slate-700 hover:bg-slate-100`;

/** pdf_editor.page_numbers.PAGE_NUMBER_POSITIONS 와 같은 순서 (격자: 위 줄 · 쪽 · 아래 줄). */
const TOP_POSITIONS = ['top_left', 'top_center', 'top_right'];
const BOTTOM_POSITIONS = ['bottom_left', 'bottom_center', 'bottom_right'];
const POSITION_LABEL = {
  top_left: '위 · 왼쪽',
  top_center: '위 · 가운데',
  top_right: '위 · 오른쪽',
  bottom_left: '아래 · 왼쪽',
  bottom_center: '아래 · 가운데',
  bottom_right: '아래 · 오른쪽',
};
const STYLES = [
  ['arabic', '1, 2, 3'],
  ['roman_lower', 'i, ii, iii'],
  ['roman_upper', 'I, II, III'],
];
const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36];
const DEFAULT_SIZE = 12;
const DEFAULT_POSITION = 'bottom_center';
const DEFAULT_MARGIN_X = 12;
const DEFAULT_MARGIN_Y = 10;
const MARGIN_MIN = 0;
const MARGIN_MAX = 30;
const PREFIX_PRESETS = [
  ['페이지', '페이지 '],
  ['Page', 'Page '],
  ['page', 'page '],
];
const SUFFIX_PRESETS = [
  ['페이지', ' 페이지'],
  ['Page', ' Page'],
  ['page', ' page'],
];
/** 원본 A4 기준 여백 미리보기 축척 (mm). */
const PAGE_W_MM = 210;
const PAGE_H_MM = 297;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function toRoman(number) {
  const table = [
    [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
    [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
  ];
  let value = Math.max(1, Math.trunc(number));
  let out = '';
  for (const [amount, symbol] of table) {
    while (value >= amount) {
      out += symbol;
      value -= amount;
    }
  }
  return out;
}

/** pdf_editor.page_numbers.format_page_number_text 와 같은 표시 문자열. */
export function formatPageNumberText(number, style, addHyphens, prefix = '', suffix = '') {
  let body;
  if (style === 'roman_lower') body = toRoman(number).toLowerCase();
  else if (style === 'roman_upper') body = toRoman(number);
  else body = String(Math.max(0, Math.trunc(number)));
  const core = addHyphens ? `- ${body} -` : body;
  return `${prefix}${core}${suffix}`;
}

function rgbToHex(rgb) {
  const parts = Array.isArray(rgb) && rgb.length >= 3 ? rgb : [0, 0, 0];
  return `#${parts
    .slice(0, 3)
    .map((v) => Math.round(clamp(Number(v) || 0, 0, 1) * 255).toString(16).padStart(2, '0'))
    .join('')}`;
}

function hexToRgb(hex) {
  const n = parseInt(String(hex).slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

function nearestSize(value) {
  return SIZES.reduce((best, size) => (Math.abs(size - value) < Math.abs(best - value) ? size : best), SIZES[0]);
}

function defaultForm(pageCount) {
  return {
    position: DEFAULT_POSITION,
    style: 'arabic',
    addHyphens: true,
    prefix: '',
    suffix: '',
    startPage: 1,
    endPage: pageCount > 0 ? pageCount : 0,
    startNumber: 1,
    fontSize: DEFAULT_SIZE,
    color: '#000000',
    background: '#ffffff',
    backgroundTransparent: true,
    marginX: DEFAULT_MARGIN_X,
    marginY: DEFAULT_MARGIN_Y,
  };
}

/** 이미 넣은 설정(engine payload)을 대화상자 값으로. 원본 PageNumberDialog._apply_options 와 같다. */
function formFromApplied(options, pageCount) {
  const pages = Math.max(1, pageCount);
  const startPage = clamp(options.startPage || 1, 1, pages);
  const endRaw = options.endPage > 0 ? options.endPage : pages;
  const endPage = clamp(endRaw, startPage, pages);
  const position = options.position === 'none' || [...TOP_POSITIONS, ...BOTTOM_POSITIONS].includes(options.position)
    ? options.position
    : DEFAULT_POSITION;
  return {
    position,
    style: STYLES.some(([id]) => id === options.style) ? options.style : 'arabic',
    addHyphens: Boolean(options.addHyphens),
    prefix: options.prefix || '',
    suffix: options.suffix || '',
    startPage,
    endPage,
    startNumber: clamp(options.startNumber || 1, 1, 9999),
    fontSize: nearestSize(Math.round(options.fontSize || DEFAULT_SIZE)),
    color: rgbToHex(options.colorRgb),
    background: rgbToHex(options.backgroundRgb ?? [1, 1, 1]),
    backgroundTransparent: Boolean(options.backgroundTransparent),
    marginX: clamp(Math.round(options.marginXmm ?? DEFAULT_MARGIN_X), MARGIN_MIN, MARGIN_MAX),
    marginY: clamp(Math.round(options.marginYmm ?? DEFAULT_MARGIN_Y), MARGIN_MIN, MARGIN_MAX),
  };
}

function toOptions(form) {
  return {
    position: form.position,
    style: form.style,
    addHyphens: form.addHyphens,
    prefix: form.prefix,
    suffix: form.suffix,
    startPage: form.startPage,
    endPage: form.endPage,
    startNumber: form.startNumber,
    fontSize: form.fontSize,
    colorRgb: hexToRgb(form.color),
    backgroundRgb: hexToRgb(form.background),
    backgroundTransparent: form.backgroundTransparent,
    marginXmm: form.marginX,
    marginYmm: form.marginY,
  };
}

/** 원본 _PageNumberPreview: A4 쪽 모형 위에 번호가 놓이는 자리를 보여 준다. */
function PageNumberPreview({ form }) {
  const none = form.position === 'none';
  const text = formatPageNumberText(form.startNumber, form.style, form.addHyphens, form.prefix, form.suffix);
  const top = form.position.startsWith('top');
  const posStyle = {};
  if (top) posStyle.top = `${(form.marginY / PAGE_H_MM) * 100}%`;
  else posStyle.bottom = `${(form.marginY / PAGE_H_MM) * 100}%`;
  if (form.position.endsWith('left')) posStyle.left = `${(form.marginX / PAGE_W_MM) * 100}%`;
  else if (form.position.endsWith('right')) posStyle.right = `${(form.marginX / PAGE_W_MM) * 100}%`;
  else {
    posStyle.left = '50%';
    posStyle.transform = 'translateX(-50%)';
  }
  return (
    <div className="relative h-[168px] w-[118px] bg-[#f3f3f3]">
      <div className="absolute bottom-2 left-2.5 right-2.5 top-2 border border-[#b0b0b0] bg-[#ececec]">
        {none ? null : (
          <span
            className="absolute whitespace-nowrap leading-none"
            style={{
              ...posStyle,
              color: form.color,
              fontSize: text.length > 10 ? 8 : 10,
              background: form.backgroundTransparent ? 'transparent' : form.background,
              padding: '1px 3px',
            }}
          >
            {text}
          </span>
        )}
      </div>
    </div>
  );
}

function NumberInput({ value, onChange, min, max, disabled, suffix }) {
  return (
    <span className="flex items-center gap-1">
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        className={`${fieldBase} w-20`}
        onChange={(event) => onChange(clamp(Math.trunc(Number(event.target.value)) || 0, min, max))}
      />
      {suffix ? <span className="text-sm text-slate-500">{suffix}</span> : null}
    </span>
  );
}

/**
 * @param {{
 *   open: boolean,
 *   pageCount: number,
 *   onClose: () => void,
 *   onApply: (options: Record<string, unknown>) => void,
 *   loadApplied?: () => Promise<Record<string, unknown> | null>,
 * }} props
 */
export default function PageNumberDialog({ open, pageCount, onClose, onApply, loadApplied }) {
  const [form, setForm] = useState(() => defaultForm(pageCount));

  // 열 때마다 기본값으로 맞추고, 이전에 넣은 설정이 있으면 그 값으로 덮는다.
  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    setForm(defaultForm(pageCount));
    if (loadApplied) {
      loadApplied()
        .then((applied) => {
          if (!cancelled && applied) setForm(formFromApplied(applied, pageCount));
        })
        .catch(() => {});
    }
    return () => {
      cancelled = true;
    };
    // loadApplied 는 매 렌더마다 새로 만들어지므로 의존성에서 뺀다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pageCount]);

  if (!open) return null;

  const none = form.position === 'none';
  const centerColumn = form.position.endsWith('center');
  const pages = Math.max(1, pageCount);
  const set = (patch) => setForm((prev) => ({ ...prev, ...patch }));

  function setStart(value) {
    const start = clamp(value, 1, pages);
    setForm((prev) => ({ ...prev, startPage: start, endPage: Math.max(prev.endPage, start) }));
  }

  function setEnd(value) {
    const end = clamp(value, 1, pages);
    setForm((prev) => ({ ...prev, endPage: end, startPage: Math.min(prev.startPage, end) }));
  }

  function submit(event) {
    event.preventDefault();
    onApply(toOptions(form));
  }

  const positionRadio = (position) => (
    <input
      key={position}
      type="radio"
      name="page-number-position"
      value={position}
      title={POSITION_LABEL[position]}
      aria-label={POSITION_LABEL[position]}
      checked={form.position === position}
      onChange={() => set({ position })}
      className="h-4 w-4 accent-app-accent"
    />
  );

  return (
    <div className={overlayClass} role="presentation">
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="page-number-title"
        className={cardClass}
        onSubmit={submit}
      >
        <h2 id="page-number-title" className="m-0 text-base font-semibold text-slate-900">
          쪽 번호 매기기
        </h2>

        <div className="mt-4 flex gap-5">
          {/* 왼쪽: 번호 위치 */}
          <div className="flex w-[190px] shrink-0 flex-col gap-2">
            <span className="text-sm font-semibold text-slate-800">번호 위치</span>
            <div className="grid grid-cols-3 justify-items-center gap-y-1 rounded-md border border-slate-300 px-2 py-2">
              {TOP_POSITIONS.map(positionRadio)}
              <div className="col-span-3 justify-self-center py-1">
                <PageNumberPreview form={form} />
              </div>
              {BOTTOM_POSITIONS.map(positionRadio)}
            </div>

            <div className="mt-1 grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1.5">
              <span className={labelClass}>가로 여백:</span>
              <NumberInput
                value={form.marginX}
                min={MARGIN_MIN}
                max={MARGIN_MAX}
                suffix="mm"
                disabled={none || centerColumn}
                onChange={(marginX) => set({ marginX })}
              />
              <span className={labelClass}>세로 여백:</span>
              <NumberInput
                value={form.marginY}
                min={MARGIN_MIN}
                max={MARGIN_MAX}
                suffix="mm"
                disabled={none}
                onChange={(marginY) => set({ marginY })}
              />
            </div>

            <label className="mt-1 flex items-center gap-2 text-sm text-slate-700">
              <input
                type="radio"
                name="page-number-position"
                value="none"
                checked={none}
                onChange={() => set({ position: 'none' })}
                className="h-4 w-4 accent-app-accent"
              />
              쪽 번호 없음
            </label>
          </div>

          {/* 가운데: 번호 모양 */}
          <div className="flex min-w-0 flex-1 flex-col gap-3">
            <span className="text-sm font-semibold text-slate-800">번호 모양</span>
            <div className="grid grid-cols-[170px_1fr] items-center gap-x-3">
              <select
                className={`${fieldBase} w-full`}
                value={form.style}
                disabled={none}
                onChange={(event) => set({ style: event.target.value })}
              >
                {STYLES.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1.5 whitespace-nowrap text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="m-0"
                  checked={form.addHyphens}
                  disabled={none}
                  onChange={(event) => set({ addHyphens: event.target.checked })}
                />
                줄표 넣기
              </label>
            </div>

            <div className="grid grid-cols-[170px_1fr] items-center gap-x-3 gap-y-2.5">
              <span className={labelClass}>접두사:</span>
              <input
                list="page-number-prefix-presets"
                className={fieldClass}
                value={form.prefix}
                placeholder="예: page "
                disabled={none}
                onChange={(event) => set({ prefix: event.target.value })}
              />
              <datalist id="page-number-prefix-presets">
                {PREFIX_PRESETS.map(([label, value]) => (
                  <option key={label} value={value} label={label} />
                ))}
              </datalist>

              <span className={labelClass}>접미사:</span>
              <input
                list="page-number-suffix-presets"
                className={fieldClass}
                value={form.suffix}
                placeholder="예: 페이지"
                disabled={none}
                onChange={(event) => set({ suffix: event.target.value })}
              />
              <datalist id="page-number-suffix-presets">
                {SUFFIX_PRESETS.map(([label, value]) => (
                  <option key={label} value={value} label={label} />
                ))}
              </datalist>

              <span className={labelClass}>쪽 번호 시작 페이지:</span>
              <NumberInput value={form.startPage} min={1} max={pages} disabled={none} onChange={setStart} />

              <span className={labelClass}>쪽 번호 끝 페이지:</span>
              <NumberInput value={form.endPage} min={1} max={pages} disabled={none} onChange={setEnd} />

              <span className={labelClass}>시작 번호:</span>
              <NumberInput
                value={form.startNumber}
                min={1}
                max={9999}
                disabled={none}
                onChange={(startNumber) => set({ startNumber })}
              />

              <span className={labelClass}>쪽 번호 크기:</span>
              <select
                className={`${fieldBase} w-24`}
                value={form.fontSize}
                disabled={none}
                onChange={(event) => set({ fontSize: Number(event.target.value) })}
              >
                {SIZES.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>

              <span className={labelClass}>쪽 번호 색상:</span>
              <input
                type="color"
                value={form.color}
                disabled={none}
                title="쪽 번호 색상"
                onChange={(event) => set({ color: event.target.value })}
                className="h-7 w-10 cursor-pointer rounded border border-slate-300 bg-white p-0.5 disabled:opacity-50"
              />

              <span className={labelClass}>배경 색상:</span>
              <span className="flex items-center gap-2">
                <input
                  type="color"
                  value={form.background}
                  disabled={none || form.backgroundTransparent}
                  title="배경 색상"
                  onChange={(event) => set({ background: event.target.value })}
                  className="h-7 w-10 cursor-pointer rounded border border-slate-300 bg-white p-0.5 disabled:opacity-50"
                />
                <label className="flex items-center gap-1.5 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={form.backgroundTransparent}
                    disabled={none}
                    onChange={(event) => set({ backgroundTransparent: event.target.checked })}
                  />
                  투명
                </label>
              </span>
            </div>
          </div>
        </div>

        {/* 실행 버튼: 창 오른쪽 아래 */}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={btnGhost} onClick={onClose}>
            취소
          </button>
          <button type="submit" className={btnPrimary}>
            넣기
          </button>
        </div>
      </form>
    </div>
  );
}
