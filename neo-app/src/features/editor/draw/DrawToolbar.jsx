import { useEffect, useRef, useState } from 'react';
import { useAnchoredPlacement } from '../../../lib/menuPlacement.js';
import NumberStepper from '../../../components/common/NumberStepper.jsx';
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
import {
  FONT_SIZES,
  SELECT_TOOL,
  SHAPE_KINDS,
  SHAPE_LABELS,
  SHAPE_TOOL_IDS,
  SHAPE_OPACITY_MIN,
  SHAPE_WIDTH_MAX,
  SHAPE_WIDTH_MIN,
  SHAPE_WIDTH_STEP,
  hasFill,
  paramsToStyle,
  snapShapeOpacity,
  snapWidth,
  styleGroupOf,
  stylePatchToParams,
} from './shapeSettings.js';

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

/** 선택 도구와 도형 아이콘. */
function ShapeIcon({ kind }) {
  switch (kind) {
    case SELECT_TOOL:
      return (
        <svg {...iconProps}>
          <path d="M5 3l10 6.5-4.5 1.2L8 15.5z" />
        </svg>
      );
    case 'line':
      return (
        <svg {...iconProps}>
          <path d="M3.5 16.5l13-13" />
        </svg>
      );
    case 'arrow':
      return (
        <svg {...iconProps}>
          <path d="M3.5 16.5l13-13" />
          <path d="M9 3.5h7.5V11" />
        </svg>
      );
    case 'rect':
      return (
        <svg {...iconProps}>
          <rect x="3" y="5" width="14" height="10" />
        </svg>
      );
    case 'ellipse':
      return (
        <svg {...iconProps}>
          <ellipse cx="10" cy="10" rx="7" ry="5" />
        </svg>
      );
    case 'polygon':
      return (
        <svg {...iconProps}>
          <path d="M10 3l7 5-2.7 9H5.7L3 8z" />
        </svg>
      );
    case 'cloud':
      return (
        <svg {...iconProps}>
          <path d="M5.5 15.5a3.2 3.2 0 010-6.4 4.5 4.5 0 018.7-1A3.6 3.6 0 0114.5 15.5z" />
        </svg>
      );
    case 'polyline':
      return (
        <svg {...iconProps}>
          <path d="M3 15l5-8 4 6 5-9" />
        </svg>
      );
    default:
      return (
        <svg {...iconProps}>
          <rect x="3" y="4" width="14" height="12" />
          <path d="M7 8h6M10 8v5" />
        </svg>
      );
  }
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

function ColorPopover({ value, onPick, onClose, allowNone = false }) {
  const ref = useRef(null);
  useAnchoredPlacement(ref);
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
  const isCustom = value != null && !MAIN_COLOR_PALETTE.includes(value);
  return (
    <div ref={ref} className="fixed left-0 top-full z-40 w-max rounded-lg border border-slate-300 bg-white p-2 shadow-lg" role="dialog" aria-label="색상">
      {allowNone ? (
        <button
          type="button"
          data-draw-color-none="1"
          onClick={() => {
            onPick(null);
            onClose();
          }}
          className={`mb-2 w-full rounded border px-2 py-1 text-left text-[12px] hover:bg-slate-50 ${value == null ? 'border-app-accent bg-app-accentSoft' : 'border-slate-300'}`}
        >
          색 없음
        </button>
      ) : null}
      <div className="grid grid-cols-4 gap-2">
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
            className={`h-6 w-6 rounded-full border ${hex === value ? 'ring-2 ring-app-accent ring-offset-1' : 'hover:scale-110'} ${hex === '#ffffff' ? 'border-slate-300' : 'border-black/10'}`}
            style={{ backgroundColor: hex }}
          />
        ))}
        <label
          title="다른 색 고르기"
          className={`relative flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-slate-300 text-[12px] text-slate-500 hover:scale-110 ${isCustom ? 'ring-2 ring-app-accent ring-offset-1' : ''}`}
          style={isCustom ? { backgroundColor: value, color: 'transparent' } : { background: 'conic-gradient(red, yellow, lime, aqua, blue, magenta, red)' }}
        >
          <input
            type="color"
            value={normalizeHex(value ?? '#000000')}
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

/** 색 견본 단추 + 누르면 열리는 팔레트. value 가 null 이면 '색 없음'. */
function ColorButton({ label, value, onPick, allowNone = false, dataKey }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative flex items-center gap-1">
      {label ? <span className="text-slate-500">{label}</span> : null}
      <button
        type="button"
        title={label || '색상'}
        aria-label={label || '색상'}
        aria-expanded={open}
        data-draw-color={dataKey || '1'}
        onClick={() => setOpen((prev) => !prev)}
        className="inline-flex h-7 items-center gap-1 rounded border border-slate-300 bg-white px-1.5 hover:bg-slate-50"
      >
        <span
          className="relative block h-4 w-4 overflow-hidden rounded-full border border-black/10"
          style={{ backgroundColor: value ?? '#ffffff' }}
        >
          {value == null ? <span className="absolute left-1/2 top-[-2px] h-5 w-px rotate-45 bg-red-500" /> : null}
        </span>
        <span className="text-[10px] text-slate-400">▾</span>
      </button>
      {open ? <ColorPopover value={value} allowNone={allowNone} onPick={onPick} onClose={() => setOpen(false)} /> : null}
    </div>
  );
}

/** 도형 설정 한 줄. style 은 막대 설정(불투명도 %), onPatch 로 바뀐 부분만 알려 준다. */
function ShapeSettings({ kind, style, onPatch }) {
  const group = styleGroupOf(kind);
  const isText = kind === 'text';
  return (
    <>
      <ColorButton label={isText ? '테두리' : '선'} value={style.color} onPick={(hex) => onPatch({ color: hex })} dataKey="line" />
      {hasFill(kind) ? <ColorButton label={isText ? '배경' : '채우기'} value={style.fill} allowNone onPick={(hex) => onPatch({ fill: hex })} dataKey="fill" /> : null}
      {isText ? (
        <>
          <ColorButton label="글자" value={style.textColor} onPick={(hex) => onPatch({ textColor: hex ?? '#000000' })} dataKey="text" />
          <label className="flex items-center gap-1" title="글자 크기">
            <span className="text-slate-500">크기</span>
            <select
              value={FONT_SIZES.includes(style.fontSize) ? style.fontSize : ''}
              data-draw-font-size="1"
              onChange={(event) => onPatch({ fontSize: Number(event.target.value) })}
              className="h-7 rounded border border-slate-300 bg-white px-1"
            >
              {FONT_SIZES.includes(style.fontSize) ? null : <option value="">{style.fontSize}</option>}
              {FONT_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        </>
      ) : null}
      <NumberStepper
        label="굵기"
        title={isText ? '테두리 굵기 (0 이면 테두리 없음)' : '굵기'}
        ariaLabel="굵기"
        dataAttr="data-draw-size"
        value={style.width}
        min={isText ? 0 : SHAPE_WIDTH_MIN}
        max={SHAPE_WIDTH_MAX}
        step={SHAPE_WIDTH_STEP}
        normalize={(v) => snapWidth(group, v)}
        onChange={(width) => onPatch({ width })}
      />
      <NumberStepper
        label="투명도"
        title="불투명도 (%)"
        ariaLabel="불투명도"
        dataAttr="data-draw-opacity"
        suffix="%"
        value={style.opacity}
        min={SHAPE_OPACITY_MIN}
        max={100}
        step={OPACITY_STEP}
        normalize={snapShapeOpacity}
        onChange={(opacity) => onPatch({ opacity })}
      />
      {isText ? null : (
        <label className="flex items-center gap-1" title="점선">
          <input type="checkbox" checked={Boolean(style.dash)} data-draw-dash="1" onChange={(event) => onPatch({ dash: event.target.checked })} />
          <span className="text-slate-500">점선</span>
        </label>
      )}
    </>
  );
}

/** 도형 목록(선·화살표·…·텍스트 상자). 열려 있을 때 표시된 글자를 누르면 바로 고른다. */
function ShapeMenu({ current, onPick, onClose }) {
  const ref = useRef(null);
  useAnchoredPlacement(ref);
  useEffect(() => {
    const onDown = (event) => {
      if (ref.current?.contains(event.target) || event.target.closest?.('[data-draw-shape-menu-button]')) return;
      onClose();
    };
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const item = SHAPE_KINDS.find((kind) => kind.key.toLowerCase() === event.key.toLowerCase());
      if (item) {
        event.preventDefault();
        event.stopPropagation();
        onPick(item.id);
      }
    };
    window.addEventListener('pointerdown', onDown, true);
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [onClose, onPick]);
  return (
    <div ref={ref} role="menu" aria-label="도형" data-draw-shape-menu="1" className="fixed left-0 top-full z-40 w-44 rounded-lg border border-slate-300 bg-white py-1 shadow-lg">
      {SHAPE_KINDS.map((kind) => (
        <button
          key={kind.id}
          type="button"
          role="menuitem"
          data-draw-shape={kind.id}
          onClick={() => onPick(kind.id)}
          className={`flex w-full items-center gap-2 px-2.5 py-1 text-left text-[12px] hover:bg-slate-100 ${current === kind.id ? 'bg-app-accentSoft text-app-accentText' : ''}`}
        >
          <ShapeIcon kind={kind.id} />
          <span className="flex-1">{kind.label}</span>
          <span className="text-slate-400">({kind.key})</span>
        </button>
      ))}
    </div>
  );
}

const toolButtonClass = (active) =>
  `inline-flex h-7 w-7 items-center justify-center rounded border ${active ? 'border-app-accent bg-app-accentSoft text-app-accentText' : 'border-transparent text-slate-600 hover:bg-slate-100'}`;

/** 그리기 모드 도구 막대. 뷰어 위쪽 가운데에 떠 있다. */
export default function DrawToolbar({ state, onChange, onDone, shapeEdit }) {
  const [shapeMenuOpen, setShapeMenuOpen] = useState(false);
  const isSelect = state.tool === SELECT_TOOL;
  const isShape = SHAPE_TOOL_IDS.includes(state.tool);
  const tool = TOOL_BUTTONS.includes(state.tool) || isSelect || isShape ? state.tool : 'pen';
  const isEraser = tool === 'eraser';
  const isInk = DRAW_TOOLS.includes(tool);
  // 지우개는 색·불투명도가 없다. 아래 값은 지우개일 때 쓰이지 않는다.
  const settings = state.tools[isInk ? tool : 'pen'];
  const limits = sliderLimits(isInk ? tool : 'pen');

  const update = (patch) =>
    onChange((prev) => (!DRAW_TOOLS.includes(prev.tool) ? prev : { ...prev, tools: { ...prev.tools, [prev.tool]: { ...prev.tools[prev.tool], ...patch } } }));
  const pickTool = (next) => {
    setShapeMenuOpen(false);
    onChange((prev) => ({ ...prev, tool: next, lastShape: SHAPE_TOOL_IDS.includes(next) ? next : prev.lastShape }));
  };

  // 도형 도구: 새로 그릴 도형의 설정은 막대 설정에, 선택한 도형의 설정은 그 도형에 바로 적용한다.
  const selectedShape = isSelect ? shapeEdit?.selectedShape : null;
  const shapeKind = isShape ? tool : selectedShape?.kind;
  const patchNewShape = (patch) => {
    const group = styleGroupOf(tool);
    onChange((prev) => ({ ...prev, shapes: { ...prev.shapes, [group]: { ...prev.shapes[group], ...patch } } }));
  };
  const shapeStyle = isShape ? state.shapes[styleGroupOf(tool)] : selectedShape ? paramsToStyle(selectedShape.params) : null;
  const patchShape = isShape ? patchNewShape : (patch) => shapeEdit?.patchSelected(stylePatchToParams(patch));

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
            className={toolButtonClass(tool === id)}
          >
            <ToolIcon tool={id} />
          </button>
        ))}
        <span className="mx-0.5 h-5 w-px bg-slate-300" />
        <button
          type="button"
          role="radio"
          aria-checked={isSelect}
          title="선택 — 도형·펜·연필·형광펜을 눌러 고르고, Delete 로 지웁니다"
          data-draw-tool={SELECT_TOOL}
          onClick={() => pickTool(SELECT_TOOL)}
          className={toolButtonClass(isSelect)}
        >
          <ShapeIcon kind={SELECT_TOOL} />
        </button>
        <div className="relative">
          <button
            type="button"
            title={`도형 — ${SHAPE_LABELS[isShape ? tool : state.lastShape]}`}
            aria-haspopup="menu"
            aria-expanded={shapeMenuOpen}
            data-draw-shape-menu-button="1"
            data-draw-tool="shape"
            onClick={() => setShapeMenuOpen((open) => !open)}
            className={`inline-flex h-7 items-center gap-0.5 rounded border px-1 ${isShape ? 'border-app-accent bg-app-accentSoft text-app-accentText' : 'border-transparent text-slate-600 hover:bg-slate-100'}`}
          >
            <ShapeIcon kind={isShape ? tool : state.lastShape} />
            <span className="text-[10px] text-slate-400">▾</span>
          </button>
          {shapeMenuOpen ? <ShapeMenu current={isShape ? tool : null} onPick={pickTool} onClose={() => setShapeMenuOpen(false)} /> : null}
        </div>
      </div>

      <span className="h-5 w-px bg-slate-300" />

      {isEraser ? (
        <div className="flex items-center gap-1">
          <NumberStepper
            label="지우개 크기"
            ariaLabel="지우개 크기"
            dataAttr="data-draw-eraser-size"
            value={state.eraserRadius}
            min={ERASER_RADIUS_MIN}
            max={ERASER_RADIUS_MAX}
            step={ERASER_RADIUS_STEP}
            normalize={snapEraserRadius}
            onChange={(radius) => onChange((prev) => ({ ...prev, eraserRadius: radius }))}
          />
          <span className="text-slate-400">획 단위로 지웁니다</span>
        </div>
      ) : isInk ? (
        <>
          <ColorButton label="" value={settings.color} onPick={(hex) => update({ color: hex ?? settings.color })} />

          <NumberStepper
            label="굵기"
            ariaLabel="굵기"
            dataAttr="data-draw-size"
            value={settings.thickness}
            min={limits.min}
            max={limits.max}
            step={limits.step}
            normalize={(v) => snapThickness(tool, v)}
            onChange={(thickness) => update({ thickness })}
          />

          <NumberStepper
            label="투명도"
            title="불투명도 (%)"
            ariaLabel="불투명도"
            dataAttr="data-draw-opacity"
            suffix="%"
            value={settings.opacity}
            min={OPACITY_STEP}
            max={100}
            step={OPACITY_STEP}
            normalize={snapOpacity}
            onChange={(opacity) => update({ opacity })}
          />
          <BrushPreview settings={settings} tool={tool} />
        </>
      ) : shapeStyle && shapeKind ? (
        <>
          {selectedShape ? <span className="font-medium text-app-accentText">{SHAPE_LABELS[shapeKind]}</span> : null}
          <ShapeSettings kind={shapeKind} style={shapeStyle} onPatch={patchShape} />
        </>
      ) : null}

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
