// 그리기 도구 설정. 값은 Whiteboard4Share 의 drawToolSettings.ts 와 같다 (단위: PDF pt / 불투명도 %).
// 저장 키는 이 앱 전용이다 (다른 앱과 같은 origin 으로 열어도 섞이지 않게 접두사를 둔다).

export const DRAW_STORAGE_KEY = 'tinypdfneo.draw';

export const HIGHLIGHTER_SIZE_MIN = 10;
export const HIGHLIGHTER_SIZE_MAX = 80;
export const HIGHLIGHTER_SIZE_STEP = 5;
export const PEN_SIZE_MIN = 0.5;
export const PEN_SIZE_MAX = 6;
export const PEN_SIZE_STEP = 0.5;
export const OPACITY_STEP = 10;

export const ERASER_RADIUS_MIN = 4;
export const ERASER_RADIUS_MAX = 40;
export const ERASER_RADIUS_STEP = 2;
export const ERASER_DEFAULT_RADIUS = 10;

export const DEFAULT_DRAW_COLOR = '#4a4a4a';
export const DEFAULT_HIGHLIGHTER_COLOR = '#ffeb3b';

/** 4x4 기본 팔레트 (15색 + 우하단 사용자 색상 선택) */
export const MAIN_COLOR_PALETTE = [
  '#4a4a4a', '#ffeb3b', '#ff9800', '#ff5722', '#e53935',
  '#e91e63', '#d81b60', '#9c27b0', '#ba68c8', '#00bcd4',
  '#1976d2', '#8bc34a', '#388e3c', '#bdbdbd', '#ffffff',
];

/** 그리는 도구(획이 남는 것). 지우개는 따로 다룬다. */
export const DRAW_TOOLS = ['pen', 'pencil', 'highlighter'];

export const TOOL_LABELS = { pen: '펜', pencil: '연필', highlighter: '형광펜', eraser: '지우개' };

export const DEFAULT_TOOL_SETTINGS = {
  pen: { thickness: 1.5, opacity: 100, color: DEFAULT_DRAW_COLOR },
  pencil: { thickness: 1.5, opacity: 70, color: DEFAULT_DRAW_COLOR },
  highlighter: { thickness: 20, opacity: 20, color: DEFAULT_HIGHLIGHTER_COLOR },
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/** 불투명도 %. 0 이면 획이 안 보이므로 최소 한 단계(10%)는 남긴다. 숫자가 아니면 100. */
export function snapOpacity(opacity) {
  const value = Number(opacity);
  return Math.round(clamp(Number.isFinite(value) ? value : 100, OPACITY_STEP, 100) / OPACITY_STEP) * OPACITY_STEP;
}

export function snapThickness(tool, thickness) {
  const value = Number(thickness);
  if (tool === 'highlighter') {
    const snapped = Math.round(clamp(Number.isFinite(value) ? value : 20, HIGHLIGHTER_SIZE_MIN, HIGHLIGHTER_SIZE_MAX) / HIGHLIGHTER_SIZE_STEP) * HIGHLIGHTER_SIZE_STEP;
    return clamp(snapped, HIGHLIGHTER_SIZE_MIN, HIGHLIGHTER_SIZE_MAX);
  }
  const snapped = Math.round(clamp(Number.isFinite(value) ? value : 1.5, PEN_SIZE_MIN, PEN_SIZE_MAX) / PEN_SIZE_STEP) * PEN_SIZE_STEP;
  return clamp(snapped, PEN_SIZE_MIN, PEN_SIZE_MAX);
}

export function snapEraserRadius(radius) {
  const value = Number(radius);
  const snapped = Math.round(clamp(Number.isFinite(value) ? value : ERASER_DEFAULT_RADIUS, ERASER_RADIUS_MIN, ERASER_RADIUS_MAX) / ERASER_RADIUS_STEP) * ERASER_RADIUS_STEP;
  return clamp(snapped, ERASER_RADIUS_MIN, ERASER_RADIUS_MAX);
}

const HEX = /^#[0-9a-f]{6}$/i;

export function normalizeHex(color, fallback = DEFAULT_DRAW_COLOR) {
  return typeof color === 'string' && HEX.test(color) ? color.toLowerCase() : fallback;
}

export function hexToRgb01(hex) {
  const value = parseInt(normalizeHex(hex).slice(1), 16);
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255];
}

/** 저장된 값(깨졌거나 비어 있을 수 있음)을 안전한 설정으로 맞춘다. */
export function normalizeDrawState(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  const tools = {};
  for (const tool of DRAW_TOOLS) {
    const base = DEFAULT_TOOL_SETTINGS[tool];
    const saved = source.tools && typeof source.tools === 'object' ? source.tools[tool] : null;
    tools[tool] = {
      thickness: snapThickness(tool, saved?.thickness ?? base.thickness),
      opacity: snapOpacity(saved?.opacity ?? base.opacity),
      color: normalizeHex(saved?.color, base.color),
    };
  }
  return {
    tool: [...DRAW_TOOLS, 'eraser'].includes(source.tool) ? source.tool : 'pen',
    tools,
    eraserRadius: snapEraserRadius(source.eraserRadius ?? ERASER_DEFAULT_RADIUS),
  };
}

export function loadDrawState() {
  try {
    return normalizeDrawState(JSON.parse(localStorage.getItem(DRAW_STORAGE_KEY) || 'null'));
  } catch {
    return normalizeDrawState(null);
  }
}

export function saveDrawState(state) {
  try {
    localStorage.setItem(DRAW_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // 저장 공간을 못 쓰면 이번 실행에서만 유지한다.
  }
}
