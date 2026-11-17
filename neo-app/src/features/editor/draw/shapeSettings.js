// 도형 도구 설정. 저장은 drawSettings.js 의 그리기 설정(tinypdfneo.draw)에 함께 들어간다. (단위: PDF pt / 불투명도 %)

/** 그리기 도구 막대의 도형 목록. key 는 목록이 열려 있을 때 누르는 글자. */
export const SHAPE_KINDS = [
  { id: 'line', label: '선', key: 'L' },
  { id: 'arrow', label: '화살표', key: 'A' },
  { id: 'rect', label: '직사각형', key: 'R' },
  { id: 'ellipse', label: '타원형', key: 'V' },
  { id: 'polygon', label: '다각형', key: 'P' },
  { id: 'cloud', label: '클라우드', key: 'O' },
  { id: 'polyline', label: '폴리라인', key: 'E' },
  { id: 'text', label: '텍스트 상자', key: 'T' },
];

export const SHAPE_TOOL_IDS = SHAPE_KINDS.map((kind) => kind.id);
export const SHAPE_LABELS = Object.fromEntries(SHAPE_KINDS.map((kind) => [kind.id, kind.label]));

/** 점을 찍어 그리는 도형. 나머지(직사각형·타원형·텍스트 상자)는 상자를 끌어 그린다. */
export const POINT_KINDS = ['line', 'arrow', 'polygon', 'cloud', 'polyline'];
export const CLOSED_KINDS = ['polygon', 'cloud'];

export function isPointKind(kind) {
  return POINT_KINDS.includes(kind);
}

export function hasFill(kind) {
  return ['rect', 'ellipse', 'polygon', 'cloud', 'text'].includes(kind);
}

export const SELECT_TOOL = 'select';

/** 모양 묶음: 텍스트 상자는 글자 설정이 있고 테두리가 기본으로 없다. 나머지 도형은 같은 설정을 나눠 쓴다. */
export function styleGroupOf(kind) {
  return kind === 'text' ? 'text' : 'shape';
}

export const SHAPE_WIDTH_MIN = 0.5;
export const SHAPE_WIDTH_MAX = 20;
export const SHAPE_WIDTH_STEP = 0.5; // 단추 한 번에 바뀌는 양. 직접 입력은 0.1 단위까지 받는다.
export const SHAPE_OPACITY_MIN = 5;
export const FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64];

export const DEFAULT_SHAPE_STYLES = {
  shape: { color: '#e53935', fill: null, width: 2, opacity: 100, dash: false },
  text: { color: '#4a4a4a', fill: null, width: 0, opacity: 100, dash: false, textColor: '#000000', fontSize: 14 },
};

const HEX = /^#[0-9a-f]{6}$/i;

function hexOr(value, fallback) {
  return typeof value === 'string' && HEX.test(value) ? value.toLowerCase() : fallback;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function snapWidth(group, value) {
  const number = Number(value);
  const min = group === 'text' ? 0 : SHAPE_WIDTH_MIN;
  const base = Number.isFinite(number) ? number : DEFAULT_SHAPE_STYLES[group].width;
  return clamp(Math.round(clamp(base, min, SHAPE_WIDTH_MAX) * 10) / 10, min, SHAPE_WIDTH_MAX);
}

export function snapShapeOpacity(value) {
  const number = Number(value);
  const base = Number.isFinite(number) ? number : 100;
  return Math.round(clamp(base, SHAPE_OPACITY_MIN, 100));
}

export function snapFontSize(value) {
  const number = Number(value);
  return Number.isFinite(number) ? clamp(Math.round(number), 4, 200) : 14;
}

/** 저장된 값(깨졌거나 비어 있을 수 있음)을 안전한 도형 설정으로 맞춘다. */
export function normalizeShapeStyles(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  const out = {};
  for (const group of ['shape', 'text']) {
    const base = DEFAULT_SHAPE_STYLES[group];
    const saved = source[group] && typeof source[group] === 'object' ? source[group] : {};
    out[group] = {
      color: hexOr(saved.color, base.color),
      fill: saved.fill === null || saved.fill === undefined ? null : hexOr(saved.fill, null),
      width: snapWidth(group, saved.width ?? base.width),
      opacity: snapShapeOpacity(saved.opacity ?? base.opacity),
      dash: group === 'text' ? false : Boolean(saved.dash),
      ...(group === 'text' ? { textColor: hexOr(saved.textColor, base.textColor), fontSize: snapFontSize(saved.fontSize ?? base.fontSize) } : {}),
    };
  }
  return out;
}

/** 도구 막대 설정(불투명도 %) → 엔진이 받는 도형 모양(불투명도 0~1). */
export function styleToParams(kind, style) {
  const params = {
    color: style.color,
    fill: hasFill(kind) ? (style.fill ?? null) : null,
    width: style.width,
    opacity: style.opacity / 100,
    dash: Boolean(style.dash),
  };
  if (kind === 'text') {
    params.textColor = style.textColor;
    params.fontSize = style.fontSize;
  }
  return params;
}

/** 엔진이 돌려준 도형 모양 → 도구 막대 설정. */
export function paramsToStyle(params) {
  return {
    color: params.color,
    fill: params.fill ?? null,
    width: params.width,
    opacity: Math.round((params.opacity ?? 1) * 100),
    dash: Boolean(params.dash),
    textColor: params.textColor ?? '#000000',
    fontSize: params.fontSize ?? 14,
  };
}

/** 도구 막대 설정 한 부분({opacity:%,...}) → 엔진 모양 한 부분. */
export function stylePatchToParams(patch) {
  const out = { ...patch };
  if ('opacity' in out) out.opacity = out.opacity / 100;
  return out;
}
