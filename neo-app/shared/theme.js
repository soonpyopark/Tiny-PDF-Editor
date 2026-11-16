/**
 * Accent theme. One hex drives every accent surface: the palette is derived
 * here and published as CSS variables, so components only reference the
 * `app-*` Tailwind tokens.
 */

export const DEFAULT_ACCENT_COLOR = '#57534e';

/** Preset swatches offered in 설정 → 일반 → 테마 색상. */
export const ACCENT_COLOR_PRESETS = [
  '#57534e',
  '#475569',
  '#2563eb',
  '#1d4ed8',
  '#0ea5e9',
  '#0d9488',
  '#059669',
  '#16a34a',
  '#65a30d',
  '#ca8a04',
  '#ea580c',
  '#dc2626',
  '#e11d48',
  '#db2777',
  '#9333ea',
  '#7c3aed',
  '#4f46e5',
];

const HEX_PATTERN = /^#[0-9a-fA-F]{6}$/;

/**
 * @param {unknown} value
 * @param {string} [fallback]
 */
export function normalizeAccentColor(value, fallback = DEFAULT_ACCENT_COLOR) {
  const text = String(value ?? '').trim();
  return HEX_PATTERN.test(text) ? text.toLowerCase() : fallback;
}

/** @param {string} hex */
function hexToRgb(hex) {
  const value = hex.replace('#', '');
  return {
    r: parseInt(value.slice(0, 2), 16),
    g: parseInt(value.slice(2, 4), 16),
    b: parseInt(value.slice(4, 6), 16),
  };
}

/** @param {number} value */
function toHexByte(value) {
  return Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, '0');
}

/**
 * Blends `hex` toward `other`; `weight` is the share of `hex` that survives.
 * @param {string} hex
 * @param {string} other
 * @param {number} weight
 */
function mix(hex, other, weight) {
  const a = hexToRgb(hex);
  const b = hexToRgb(other);
  return `#${[
    toHexByte(a.r * weight + b.r * (1 - weight)),
    toHexByte(a.g * weight + b.g * (1 - weight)),
    toHexByte(a.b * weight + b.b * (1 - weight)),
  ].join('')}`;
}

/** Tailwind needs bare `r g b` channels so `bg-app-accent/50` works. */
function toChannels(hex) {
  const { r, g, b } = hexToRgb(hex);
  return `${r} ${g} ${b}`;
}

/**
 * @param {unknown} accent
 * @returns {Record<string, string>} CSS variable name → `r g b` channels
 */
export function accentCssVariables(accent) {
  const base = normalizeAccentColor(accent);
  return {
    '--app-accent': toChannels(base),
    '--app-accent-hover': toChannels(mix(base, '#000000', 0.82)),
    '--app-accent-soft': toChannels(mix(base, '#ffffff', 0.1)),
    '--app-accent-soft-hover': toChannels(mix(base, '#ffffff', 0.18)),
    '--app-accent-border': toChannels(mix(base, '#ffffff', 0.35)),
    '--app-accent-text': toChannels(mix(base, '#000000', 0.55)),
    '--app-sidebar': toChannels(mix(base, '#0f172a', 0.14)),
    '--app-sidebar-hover': toChannels(mix(base, '#334155', 0.16)),
  };
}
