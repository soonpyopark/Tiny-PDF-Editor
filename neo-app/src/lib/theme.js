import { DEFAULT_ACCENT_COLOR, accentCssVariables, normalizeAccentColor } from '../../shared/theme.js';

/**
 * Paints the accent palette onto `:root`. Every `app-*` Tailwind token reads
 * these variables, so one call recolours the whole app without a re-render.
 *
 * @param {unknown} accent
 * @returns {string} the accent that was applied
 */
export function applyAccentColor(accent) {
  const color = normalizeAccentColor(accent, DEFAULT_ACCENT_COLOR);
  const root = document.documentElement;
  if (root.dataset.accentColor === color) return color;

  for (const [name, value] of Object.entries(accentCssVariables(color))) {
    root.style.setProperty(name, value);
  }
  root.dataset.accentColor = color;
  return color;
}
