import { DEFAULT_ACCENT_COLOR, normalizeAccentColor } from '../shared/theme.js';
import { parsePort } from '../shared/serverConfig.js';
import { statePath } from './context.js';
import { readJsonSync, withFileLock, writeJsonSync } from './jsonStore.js';

const SETTINGS_FILE = 'settings.json';

/**
 * @typedef {{
 *   version: 1,
 *   accentColor: string,
 *   startupUpdateCheck: boolean,
 *   closeToTray: boolean,
 *   webServerPort: number | null,
 * }} AppSettings
 */

/** @returns {AppSettings} */
function defaultSettings() {
  return {
    version: 1,
    accentColor: DEFAULT_ACCENT_COLOR,
    startupUpdateCheck: true,
    closeToTray: true,
    webServerPort: null,
  };
}

/**
 * Coerces anything read from disk / the API into a valid settings object.
 * Unknown keys (옛 회원·HTTPS·백업 등) are dropped.
 *
 * @param {any} raw
 * @returns {AppSettings}
 */
function normalizeSettings(raw) {
  const base = defaultSettings();
  const src = raw && typeof raw === 'object' ? raw : {};
  return {
    version: 1,
    accentColor: normalizeAccentColor(src.accentColor, base.accentColor),
    startupUpdateCheck: src.startupUpdateCheck !== false,
    closeToTray: src.closeToTray !== false,
    webServerPort: parsePort(src.webServerPort),
  };
}

/** @type {AppSettings | null} */
let cache = null;

function load() {
  if (!cache) cache = normalizeSettings(readJsonSync(statePath(SETTINGS_FILE), {}));
  return cache;
}

/** @returns {AppSettings} */
export function getSettings() {
  return structuredClone(load());
}

/** Fields exposed with app.info (theme + startup behaviour). */
export function getPublicSettings() {
  const { accentColor, startupUpdateCheck } = load();
  return { accentColor, startupUpdateCheck };
}

/**
 * @param {Partial<AppSettings>} patch
 * @returns {Promise<AppSettings>}
 */
export function updateSettings(patch) {
  return withFileLock(statePath(SETTINGS_FILE), () => {
    const current = load();
    const next = normalizeSettings({ ...current, ...patch });
    writeJsonSync(statePath(SETTINGS_FILE), next);
    cache = next;
    return structuredClone(next);
  });
}
