import { useEffect, useRef, useState } from 'react';
import {
  DRAW_TOOLS,
  ERASER_RADIUS_MAX,
  ERASER_RADIUS_MIN,
  ERASER_RADIUS_STEP,
  HIGHLIGHTER_SIZE_MAX,
  HIGHLIGHTER_SIZE_MIN,
  HIGHLIGHTER_SIZE_STEP,
  MAIN_COLOR_PALETTE,
  OPACITY_STEP,
  PEN_SIZE_MAX,
  PEN_SIZE_MIN,
  PEN_SIZE_STEP,
  TOOL_LABELS,
  normalizeHex,
  snapEraserRadius,
  snapOpacity,
  snapThickness,
} from './drawSettings.js';

const TOOL_BUTTONS = [...DRAW_TOOLS, 'eraser'];

const iconProps = { viewBox: '0 0 20 20', width: 18, height: 18, fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };

function ToolIcon({ tool }) {
  if (tool === 'eraser') {
    return (
      <svg {...iconProps}>
        <path d="M8 16l-4-4 8-8 6 6-6 6z" />
        <path d="M6 9l6 6" />
        <path d="M8 16h9" />
      </svg>
    );
  }
  if (tool === 'pencil') {
    return (
      <svg {...iconProps}>
        <path d="M4 16l1-4L14 3l3 3-9 9z" />
        <path d="M12.5 4.5l3 3" />
      </svg>
    );
  }
  if (tool === 'highlighter') {
    return (
      <svg {...iconProps}>
        <path d="M11 3l6 6-6 6-6-6z" />
        <path d="M5 11l-2 5 5-1" />
        <path d="M3 18h6" />
      </svg>
    );
  }
  return (
    <svg {...iconProps}>
      <path d="M10 2l4 5-4 11-4-11z" />
      <circle cx="10" cy="9" r="1" />
    </svg>
  );
}

function sliderLimits(tool) {
  return tool === 'highlighter'
    ? { min: HIGHLIGHTER_SIZE_MIN, max: HIGHLIGHTER_SIZE_MAX, step: HIGHLIGHTER_SIZE_STEP }
    : { min: PEN_SIZE_MIN, max: PEN_SIZE_MAX, step: PEN_SIZE_STEP };
}

/** 현재 붓의 굵기·색·불투명도를 한눈에 보여 주는 미리보기. */
function BrushPreview({ settings, tool }) {
  const size = Math.min(22, Math.max(2, tool === 'highlighter' ? settings.thickness * 0.7 : settings.thickness * 2.2));
  return (
    <span className="relative inline-flex h-6 w-6 items-center justify-center rounded border border-slate-200 bg-white" aria-hidden="true">
      <span
        className="block rounded-full"
        style={{ width: size, height: size, backgroundColor: settings.color, opacity: settings.opacity / 100, boxShadow: settings.color === '#ffffff' ? 'inset 0 0 0 1px #cbd5e1' : undefined }}
      />
    </span>
  );
}

function ColorPopover({ value, onPick, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const onDown = (event) => {
      if (ref.current?.contains(event.target)) return;
      onClose();
    };
    // 팔레트가 열려 있을 때 Esc 는 팔레트만 닫는다 (그리기 끝내기로 번지지 않게).
    const onKey = (event) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    window.addEventListener('pointerdown', onDown, true);
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [onClose]);
  const isCustom = !MAIN_COLOR_PALETTE.includes(value);
  return (
    <div ref={ref} className="absolute left-0 top-full z-40 mt-1.5 rounded-lg border border-slate-300 bg-white p-2 shadow-lg" role="dialog" aria-label="색상">
      <div className="grid grid-cols-4 gap-1.5">
        {MAIN_COLOR_PALETTE.map((hex) => (
          <button
            key={hex}
            type="button"
            title={hex}
            aria-label={`색 ${hex}`}
            aria-pressed={hex === value}
            onClick={() => {
              onPick(hex);
              onClose();
            }}
            className={`h-6 w-6 rounded-full border ${hex === value ? 'ring-2 ring-sky-500 ring-offset-1' : 'hover:scale-110'} ${hex === '#ffffff' ? 'border-slate-300' : 'border-black/10'}`}
            style={{ backgroundColor: hex }}
          />
        ))}
        <label
          title="다른 색 고르기"
          className={`relative flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-slate-300 text-[12px] text-slate-500 hover:scale-110 ${isCustom ? 'ring-2 ring-sky-500 ring-offset-1' : ''}`}
          style={isCustom ? { backgroundColor: value, color: 'transparent' } : { background: 'conic-gradient(red, yellow, lime, aqua, blue, magenta, red)' }}
        >
          <input
            type="color"
            value={normalizeHex(value)}
            onChange={(event) => onPick(normalizeHex(event.target.value))}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
            aria-label="다른 색 고르기"
          />
          +
        </label>
      </div>
    </div>
  );
}

const sliderClass = 'h-[18px] w-[84px] accent-sky-600';

/** 그리기 모드 도구 막대. 뷰어 위쪽 가운데에 떠 있다. */
export default function DrawToolbar({ state, onChange, onDone }) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const tool = TOOL_BUTTONS.includes(state.tool) ? state.tool : 'pen';
  const isEraser = tool === 'eraser';
  // 지우개는 색·불투명도가 없다. 아래 값은 지우개일 때 쓰이지 않는다.
  const settings = state.tools[isEraser ? 'pen' : tool];
  const limits = sliderLimits(isEraser ? 'pen' : tool);

  const update = (patch) =>
    onChange((prev) => (prev.tool === 'eraser' ? prev : { ...prev, tools: { ...prev.tools, [prev.tool]: { ...prev.tools[prev.tool], ...patch } } }));
  const pickTool = (next) => {
    setPaletteOpen(false);
    onChange((prev) => ({ ...prev, tool: next }));
  };

  return (
    <div
      data-draw-toolbar="1"
      className="pointer-events-auto absolute inset-x-0 top-2 z-30 mx-auto flex w-max max-w-[calc(100%-1rem)] flex-wrap items-center gap-2 rounded-lg border border-slate-300 bg-white/95 px-2 py-1.5 text-[12px] text-slate-700 shadow-md"
    >
      <div className="flex items-center gap-1" role="radiogroup" aria-label="그리기 도구">
        {TOOL_BUTTONS.map((id) => (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={tool === id}
            title={TOOL_LABELS[id]}
            data-draw-tool={id}
            onClick={() => pickTool(id)}
            className={`inline-flex h-7 w-7 items-center justify-center rounded border ${tool === id ? 'border-sky-500 bg-sky-50 text-sky-700' : 'border-transparent text-slate-600 hover:bg-slate-100'}`}
          >
            <ToolIcon tool={id} />
          </button>
        ))}
      </div>

      <span className="h-5 w-px bg-slate-300" />

      {isEraser ? (
        <label className="flex items-center gap-1" title="지우개 크기">
          <span className="text-slate-500">지우개 크기</span>
          <input
            type="range"
            min={ERASER_RADIUS_MIN}
            max={ERASER_RADIUS_MAX}
            step={ERASER_RADIUS_STEP}
            value={state.eraserRadius}
            aria-label="지우개 크기"
            data-draw-eraser-size="1"
            onChange={(event) => onChange((prev) => ({ ...prev, eraserRadius: snapEraserRadius(Number(event.target.value)) }))}
            onPointerUp={(event) => event.currentTarget.blur()}
            className={sliderClass}
          />
          <span className="w-6 text-right tabular-nums text-slate-500">{state.eraserRadius}</span>
          <span className="text-slate-400">획 단위로 지웁니다</span>
        </label>
      ) : (
      <>
      <div className="relative flex items-center gap-1.5">
        <button
          type="button"
          title="색상"
          aria-label="색상"
          aria-expanded={paletteOpen}
          data-draw-color="1"
          onClick={() => setPaletteOpen((open) => !open)}
          className="inline-flex h-7 items-center gap-1 rounded border border-slate-300 bg-white px-1.5 hover:bg-slate-50"
        >
          <span
            className="block h-4 w-4 rounded-full border border-black/10"
            style={{ backgroundColor: settings.color }}
          />
          <span className="text-[10px] text-slate-400">▾</span>
        </button>
        {paletteOpen ? (
          <ColorPopover value={settings.color} onPick={(hex) => update({ color: hex })} onClose={() => setPaletteOpen(false)} />
        ) : null}
      </div>

      <label className="flex items-center gap-1" title="굵기">
        <span className="text-slate-500">굵기</span>
        <input
          type="range"
          min={limits.min}
          max={limits.max}
          step={limits.step}
          value={settings.thickness}
          aria-label="굵기"
          data-draw-size="1"
          onChange={(event) => update({ thickness: snapThickness(tool, Number(event.target.value)) })}
          onPointerUp={(event) => event.currentTarget.blur()}
          className={sliderClass}
        />
        <span className="w-6 text-right tabular-nums text-slate-500">{settings.thickness}</span>
      </label>

      <label className="flex items-center gap-1" title="불투명도">
        <span className="text-slate-500">투명도</span>
        <input
          type="range"
          min={OPACITY_STEP}
          max={100}
          step={OPACITY_STEP}
          value={settings.opacity}
          aria-label="불투명도"
          data-draw-opacity="1"
          onChange={(event) => update({ opacity: snapOpacity(Number(event.target.value)) })}
          onPointerUp={(event) => event.currentTarget.blur()}
          className={sliderClass}
        />
        <span className="w-9 text-right tabular-nums text-slate-500">{settings.opacity}%</span>
      </label>

      <BrushPreview settings={settings} tool={tool} />
      </>
      )}

      <span className="h-5 w-px bg-slate-300" />

      <button
        type="button"
        className="rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50"
        title="그리기 끝내기 (Esc)"
        onClick={onDone}
      >
        끝내기
      </button>
    </div>
  );
}
