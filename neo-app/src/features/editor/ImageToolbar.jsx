import { useEffect, useRef, useState } from 'react';
import { useAnchoredPlacement } from '../../lib/menuPlacement.js';
import NumberStepper from '../../components/common/NumberStepper.jsx';
import { mmFromPt, ptFromMm, rectSize } from './imageEditMath.js';

const btn =
  'inline-flex h-7 min-w-7 items-center justify-center gap-1 rounded border border-transparent px-1.5 text-[12px] text-slate-700 hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-transparent';
const btnOn = 'border-sky-500 bg-sky-50 text-sky-700';
const panelBtn = 'rounded border border-slate-300 bg-white px-2 py-1 text-[12px] hover:bg-slate-50 disabled:opacity-40';
const sliderClass = 'h-[18px] w-[110px]';

const iconProps = { viewBox: '0 0 20 20', width: 16, height: 16, fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };

function Icon({ name }) {
  if (name === 'ccw')
    return (
      <svg {...iconProps}>
        <path d="M5 8a6 6 0 1 1-1 5" />
        <path d="M5 3v5h5" />
      </svg>
    );
  if (name === 'cw')
    return (
      <svg {...iconProps}>
        <path d="M15 8a6 6 0 1 0 1 5" />
        <path d="M15 3v5h-5" />
      </svg>
    );
  if (name === 'flipx')
    return (
      <svg {...iconProps}>
        <path d="M10 3v14" strokeDasharray="2 2" />
        <path d="M8 6 3 14h5z" />
        <path d="M12 6l5 8h-5z" />
      </svg>
    );
  return (
    <svg {...iconProps}>
      <path d="M3 10h14" strokeDasharray="2 2" />
      <path d="M6 8 14 3v5z" transform="rotate(90 10 10)" />
      <path d="M6 12l8 5v-5z" transform="rotate(90 10 10)" />
    </svg>
  );
}

/** 슬라이더. debounce 가 있으면 멈춘 뒤에 값을 낸다(엔진 왕복이 필요한 값). */
function Slider({ label, value, min, max, step = 1, suffix = '', debounce = 0, onChange, testId }) {
  const [local, setLocal] = useState(value);
  const timer = useRef(0);
  useEffect(() => setLocal(value), [value]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <label className="flex items-center gap-2">
      <span className="w-14 shrink-0 text-slate-500">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        data-img-slider={testId}
        aria-label={label}
        className={sliderClass}
        onChange={(event) => {
          const next = Number(event.target.value);
          setLocal(next);
          window.clearTimeout(timer.current);
          if (debounce) timer.current = window.setTimeout(() => onChange(next), debounce);
          else onChange(next);
        }}
        onPointerUp={(event) => event.currentTarget.blur()}
      />
      <span className="w-10 text-right tabular-nums text-slate-500">
        {local}
        {suffix}
      </span>
    </label>
  );
}

/** 숫자 칸. Enter/포커스를 잃을 때 값을 낸다. */
function NumberField({ label, value, disabled, onCommit, testId, suffix = 'mm' }) {
  const shown = Number.isFinite(value) ? (Math.round(value * 10) / 10).toString() : '';
  const [text, setText] = useState(shown);
  useEffect(() => setText(shown), [shown]);
  const apply = () => {
    const parsed = Number(text);
    if (Number.isFinite(parsed) && text.trim() !== '') onCommit(parsed);
    else setText(shown);
  };
  return (
    <label className="flex items-center gap-1">
      <span className="w-8 text-slate-500">{label}</span>
      <input
        type="text"
        inputMode="decimal"
        value={text}
        disabled={disabled}
        data-img-field={testId}
        aria-label={label}
        className="h-6 w-16 rounded border border-slate-300 px-1 text-right tabular-nums disabled:bg-slate-50"
        onChange={(event) => setText(event.target.value)}
        onBlur={apply}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            event.stopPropagation();
            apply();
          } else if (event.key === 'Escape') {
            event.stopPropagation();
            setText(shown);
          }
        }}
      />
      <span className="text-slate-400">{suffix}</span>
    </label>
  );
}

function Panel({ children, wide }) {
  const ref = useRef(null);
  useAnchoredPlacement(ref);
  return (
    <div
      ref={ref}
      role="dialog"
      className={`fixed left-0 top-full z-40 flex w-max flex-col gap-2 rounded-lg border border-slate-300 bg-white p-3 text-[12px] text-slate-700 shadow-lg ${wide ? 'min-w-[260px]' : ''}`}
    >
      {children}
    </div>
  );
}

const rgbToHex = ([r, g, b]) => `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;
const hexToRgb = (hex) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return [255, 255, 255];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

/**
 * 이미지를 고르면 뜨는 도구 막대. 뷰어 위쪽 가운데에 떠 있다.
 * 모든 변경은 확정(완료/Enter/바깥 클릭) 전까지 PDF 에 반영되지 않는다.
 */
export default function ImageToolbar({ controller, pageCount, confirm }) {
  const [open, setOpen] = useState(/** @type {null | string} */ (null));
  const [pagesText, setPagesText] = useState('');
  const rootRef = useRef(null);
  const items = controller.items;
  const primary = items[items.length - 1];

  // 패널 밖을 누르면 패널만 닫는다(이미지 확정과는 별개).
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event) => {
      if (rootRef.current?.contains(event.target)) return;
      setOpen(null);
    };
    window.addEventListener('pointerdown', onDown, true);
    return () => window.removeEventListener('pointerdown', onDown, true);
  }, [open]);

  if (!primary) return null;
  const p = primary.params;
  const locked = Boolean(p.lock);
  const size = rectSize(primary.rect);
  const patch = (value) => void controller.patchSelected(value);
  const toggle = (name) => setOpen((cur) => (cur === name ? null : name));
  const multi = items.length > 1;
  const crop = p.crop;
  const cropSet = (index, percent) => {
    const next = [...crop];
    next[index] = percent / 100;
    patch({ crop: next });
  };

  return (
    <div
      ref={rootRef}
      data-img-overlay="1"
      data-img-toolbar="1"
      className="pointer-events-auto absolute inset-x-0 top-2 z-30 mx-auto flex w-max max-w-[calc(100%-1rem)] flex-wrap items-center gap-1 rounded-lg border border-slate-300 bg-white/95 px-2 py-1.5 text-[12px] text-slate-700 shadow-md"
    >
      <span className="px-1 text-slate-500" data-img-count={items.length}>
        이미지{multi ? ` ${items.length}개` : ''}
      </span>
      <span className="h-5 w-px bg-slate-300" />
      <button type="button" className={btn} title="왼쪽으로 90° 회전" data-img-act="rotateL" onClick={() => patch({ rotate: -90 })}>
        <Icon name="ccw" />
      </button>
      <button type="button" className={btn} title="오른쪽으로 90° 회전" data-img-act="rotateR" onClick={() => patch({ rotate: 90 })}>
        <Icon name="cw" />
      </button>
      <button type="button" className={btn} title="좌우 뒤집기" data-img-act="flipX" onClick={() => patch({ flip: 'x' })}>
        <Icon name="flipx" />
      </button>
      <button type="button" className={btn} title="상하 뒤집기" data-img-act="flipY" onClick={() => patch({ flip: 'y' })}>
        <Icon name="flipy" />
      </button>
      <span className="h-5 w-px bg-slate-300" />
      <NumberStepper
        label="투명도"
        ariaLabel="투명도"
        dataAttr="data-img-opacity"
        suffix="%"
        value={p.op}
        min={5}
        max={100}
        step={5}
        normalize={(v) => Math.min(100, Math.max(5, Math.round(v)))}
        onChange={(v) => patch({ op: v })}
      />
      <span className="h-5 w-px bg-slate-300" />

      <div className="relative">
        <button type="button" className={`${btn} ${p.bg.on || open === 'bg' ? btnOn : ''}`} data-img-act="bg" aria-expanded={open === 'bg'} onClick={() => toggle('bg')}>
          배경 투명 ▾
        </button>
        {open === 'bg' ? (
          <Panel>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={p.bg.on}
                data-img-check="bgOn"
                onChange={(event) => patch({ bg: { on: event.target.checked } })}
              />
              <span>배경색을 투명하게</span>
            </label>
            <Slider label="허용 오차" value={p.bg.tol} min={0} max={100} debounce={150} testId="bgTol" onChange={(v) => patch({ bg: { on: true, tol: v } })} />
            <Slider label="부드럽게" value={p.bg.soft} min={0} max={100} debounce={150} testId="bgSoft" onChange={(v) => patch({ bg: { on: true, soft: v } })} />
            <div className="flex items-center gap-2">
              <span className="w-14 text-slate-500">배경색</span>
              <label className="relative inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded border border-slate-300" style={{ backgroundColor: rgbToHex(p.bg.color) }} title="색 고르기">
                <input
                  type="color"
                  value={rgbToHex(p.bg.color)}
                  className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                  aria-label="배경색 고르기"
                  onChange={(event) => patch({ bg: { on: true, color: hexToRgb(event.target.value) } })}
                />
              </label>
              <button type="button" className={`${panelBtn} ${controller.eyedrop ? btnOn : ''}`} data-img-act="eyedrop" onClick={() => controller.setEyedrop(!controller.eyedrop)}>
                스포이트
              </button>
              <button type="button" className={panelBtn} onClick={() => patch({ bg: { on: true, color: [255, 255, 255] } })}>
                흰색
              </button>
            </div>
            {controller.eyedrop ? <p className="m-0 text-[11px] text-sky-700">이미지에서 투명하게 할 배경 부분을 클릭하세요.</p> : null}
          </Panel>
        ) : null}
      </div>

      <div className="relative">
        <button type="button" className={`${btn} ${open === 'crop' ? btnOn : ''}`} data-img-act="crop" aria-expanded={open === 'crop'} onClick={() => toggle('crop')}>
          자르기 ▾
        </button>
        {open === 'crop' ? (
          <Panel>
            <Slider label="왼쪽" value={Math.round(crop[0] * 100)} min={0} max={90} suffix="%" testId="cropL" onChange={(v) => cropSet(0, v)} />
            <Slider label="위쪽" value={Math.round(crop[1] * 100)} min={0} max={90} suffix="%" testId="cropT" onChange={(v) => cropSet(1, v)} />
            <Slider label="오른쪽" value={Math.round(crop[2] * 100)} min={0} max={90} suffix="%" testId="cropR" onChange={(v) => cropSet(2, v)} />
            <Slider label="아래쪽" value={Math.round(crop[3] * 100)} min={0} max={90} suffix="%" testId="cropB" onChange={(v) => cropSet(3, v)} />
            <div>
              <button type="button" className={panelBtn} data-img-act="cropReset" onClick={() => patch({ cropReset: true })}>
                자르기 초기화
              </button>
            </div>
          </Panel>
        ) : null}
      </div>

      <div className="relative">
        <button type="button" className={`${btn} ${p.adj.bright || p.adj.contrast || p.adj.gray || open === 'adj' ? btnOn : ''}`} data-img-act="adj" aria-expanded={open === 'adj'} onClick={() => toggle('adj')}>
          색 보정 ▾
        </button>
        {open === 'adj' ? (
          <Panel>
            <Slider label="밝기" value={p.adj.bright} min={-100} max={100} debounce={150} testId="bright" onChange={(v) => patch({ adj: { bright: v } })} />
            <Slider label="대비" value={p.adj.contrast} min={-100} max={100} debounce={150} testId="contrast" onChange={(v) => patch({ adj: { contrast: v } })} />
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={p.adj.gray} data-img-check="gray" onChange={(event) => patch({ adj: { gray: event.target.checked } })} />
              <span>흑백</span>
            </label>
            <div>
              <button type="button" className={panelBtn} onClick={() => patch({ adj: { bright: 0, contrast: 0, gray: false } })}>
                보정 초기화
              </button>
            </div>
          </Panel>
        ) : null}
      </div>

      <span className="h-5 w-px bg-slate-300" />

      <div className="relative">
        <button type="button" className={`${btn} ${open === 'size' ? btnOn : ''}`} data-img-act="size" aria-expanded={open === 'size'} onClick={() => toggle('size')}>
          크기·위치 ▾
        </button>
        {open === 'size' ? (
          <Panel wide>
            <p className="m-0 text-[11px] text-slate-400">비율은 유지됩니다.{multi ? ' (마지막으로 고른 이미지 기준)' : ''}</p>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
              <NumberField label="가로" value={mmFromPt(size.width)} disabled={locked} testId="width" onCommit={(mm) => controller.transformPrimary('width', ptFromMm(mm))} />
              <NumberField label="세로" value={mmFromPt(size.height)} disabled={locked} testId="height" onCommit={(mm) => controller.transformPrimary('height', ptFromMm(mm))} />
              <NumberField label="X" value={mmFromPt(primary.rect[0])} disabled={locked} testId="x" onCommit={(mm) => controller.transformPrimary('x', ptFromMm(mm))} />
              <NumberField label="Y" value={mmFromPt(primary.rect[1])} disabled={locked} testId="y" onCommit={(mm) => controller.transformPrimary('y', ptFromMm(mm))} />
            </div>
            <div className="flex flex-wrap gap-1">
              {[
                ['fitWidth', '쪽 너비'],
                ['fitHeight', '쪽 높이'],
                ['contain', '쪽 안에 맞춤'],
                ['original', '원본 크기'],
                ['half', '50%'],
                ['double', '200%'],
              ].map(([mode, label]) => (
                <button key={mode} type="button" className={panelBtn} disabled={locked} data-img-preset={mode} onClick={() => controller.transformPrimary('preset', mode)}>
                  {label}
                </button>
              ))}
            </div>
          </Panel>
        ) : null}
      </div>

      <div className="relative">
        <button type="button" className={`${btn} ${open === 'align' ? btnOn : ''}`} data-img-act="align" aria-expanded={open === 'align'} onClick={() => toggle('align')}>
          정렬 ▾
        </button>
        {open === 'align' ? (
          <Panel>
            <div className="grid grid-cols-3 gap-1">
              {[
                ['left', '왼쪽'],
                ['centerX', '가로 가운데'],
                ['right', '오른쪽'],
                ['top', '위'],
                ['centerY', '세로 가운데'],
                ['bottom', '아래'],
              ].map(([how, label]) => (
                <button key={how} type="button" className={panelBtn} disabled={locked} data-img-align={how} onClick={() => controller.alignSelected(how)}>
                  {label}
                </button>
              ))}
            </div>
            <button type="button" className={panelBtn} disabled={locked} data-img-align="center" onClick={() => controller.alignSelected('center')}>
              쪽 가운데
            </button>
          </Panel>
        ) : null}
      </div>

      <div className="relative">
        <button type="button" className={`${btn} ${open === 'more' || locked ? btnOn : ''}`} data-img-act="more" aria-expanded={open === 'more'} onClick={() => toggle('more')}>
          더보기 ▾
        </button>
        {open === 'more' ? (
          <Panel wide>
            <div className="flex flex-wrap gap-1">
              <button type="button" className={panelBtn} data-img-act="copy" onClick={() => void controller.copySelected()}>
                복사 (Ctrl+C)
              </button>
              <button type="button" className={panelBtn} data-img-act="cut" onClick={() => void controller.cutSelected()}>
                잘라내기
              </button>
              <button type="button" className={panelBtn} data-img-act="duplicate" onClick={() => void controller.duplicateSelected()}>
                복제 (Ctrl+D)
              </button>
            </div>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={locked} data-img-check="lock" onChange={(event) => patch({ lock: event.target.checked })} />
              <span>잠금 (실수로 움직이지 않게)</span>
            </label>
            <div className="flex flex-col gap-1 border-t border-slate-200 pt-2">
              <span className="text-slate-500">다른 쪽에도 같은 자리에 넣기</span>
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={pagesText}
                  placeholder="예: 2-5, 8"
                  data-img-field="pages"
                  aria-label="적용할 쪽"
                  className="h-6 w-28 rounded border border-slate-300 px-1"
                  onChange={(event) => setPagesText(event.target.value)}
                  onKeyDown={(event) => event.stopPropagation()}
                />
                <button type="button" className={panelBtn} data-img-act="applyRange" disabled={!pagesText.trim()} onClick={() => void controller.applyToPages(pagesText)}>
                  이 쪽들에
                </button>
                <button type="button" className={panelBtn} data-img-act="applyAll" disabled={pageCount < 2} onClick={() => void controller.applyToPages('all')}>
                  모든 쪽에
                </button>
              </div>
            </div>
            <div className="flex flex-col gap-1 border-t border-slate-200 pt-2">
              <button
                type="button"
                className={panelBtn}
                data-img-act="behind"
                onClick={async () => {
                  const ok = await confirm({
                    title: '본문 글 아래로 보내기',
                    body: '이미지를 본문 글과 도형 뒤로 보내 쪽에 굳힙니다.\n굳힌 뒤에는 이미지로 다시 고칠 수 없습니다(실행 취소는 가능).',
                  });
                  if (ok) void controller.flatten(true);
                }}
              >
                본문 글 아래로 보내기 (굳힘)
              </button>
              <button
                type="button"
                className={panelBtn}
                data-img-act="flatten"
                onClick={async () => {
                  const ok = await confirm({
                    title: '쪽 내용으로 굳히기',
                    body: '이미지를 쪽 내용으로 굳힙니다.\n굳힌 뒤에는 이미지로 다시 고칠 수 없습니다(실행 취소는 가능).',
                  });
                  if (ok) void controller.flatten(false);
                }}
              >
                쪽 내용으로 굳히기
              </button>
            </div>
          </Panel>
        ) : null}
      </div>

      <span className="h-5 w-px bg-slate-300" />
      <button type="button" className={`${btn} text-red-600`} title="삭제 (Delete)" data-img-act="delete" onClick={() => void controller.deleteSelected()}>
        삭제
      </button>
      <button
        type="button"
        className="rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50"
        title="완료 (Enter) · Esc 는 이번 편집 취소"
        data-img-act="done"
        onClick={() => void controller.commit()}
      >
        완료
      </button>
    </div>
  );
}
