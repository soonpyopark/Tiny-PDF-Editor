import { DEFAULT_ACCENT_COLOR, normalizeAccentColor } from '../shared/theme.js';
import { normalizeAllowedIpCidrs } from '../shared/ipCidrCore.js';
import { normalizeHttpsEnabled, normalizeTlsHostnames } from '../shared/httpsConfig.js';
import { normalizeServerMode, parsePort } from '../shared/serverConfig.js';
import { statePath } from './context.js';
import { readJsonSync, withFileLock, writeJsonSync } from './jsonStore.js';

const SETTINGS_FILE = 'settings.json';

/**
 * @typedef {{
 *   autoEnabled: boolean,
 *   intervalHours: number,
 *   keepCount: number,
 *   lastRunAt: number | null,
 * }} BackupSettings
 *
 * @typedef {{
 *   version: 1,
 *   accentColor: string,
 *   loginLockoutEnabled: boolean,
 *   startupUpdateCheck: boolean,
 *   closeToTray: boolean,
 *   webServerPort: number | null,
 *   webServerMode: import('../shared/serverConfig.js').ServerMode | null,
 *   httpsEnabled: boolean,
 *   tlsHostnames: string[],
 *   allowedIpCidrs: import('../shared/ipCidrCore.js').AllowedIpEntry[],
 *   backup: BackupSettings,
 * }} AppSettings
 */

/** @returns {AppSettings} */
function defaultSettings() {
  return {
    version: 1,
    accentColor: DEFAULT_ACCENT_COLOR,
    loginLockoutEnabled: true,
    startupUpdateCheck: true,
    closeToTray: true,
    webServerPort: null,
    webServerMode: null,
    httpsEnabled: false,
    tlsHostnames: [],
    allowedIpCidrs: [],
    backup: { autoEnabled: false, intervalHours: 24, keepCount: 10, lastRunAt: null },
  };
}

/**
 * @param {unknown} value
 * @param {number} min
 * @param {number} max
 * @param {number} fallback
 */
function clampInt(value, min, max, fallback) {
  const n = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/**
 * Coerces anything read from disk / the API into a valid settings object.
 * Unknown keys are dropped, so a new setting must be added here.
 *
 * @param {any} raw
 * @returns {AppSettings}
 */
function normalizeSettings(raw) {
  const base = defaultSettings();
  const src = raw && typeof raw === 'object' ? raw : {};
  const backup = src.backup && typeof src.backup === 'object' ? src.backup : {};
  return {
    version: 1,
    accentColor: normalizeAccentColor(src.accentColor, base.accentColor),
    loginLockoutEnabled: src.loginLockoutEnabled !== false,
    startupUpdateCheck: src.startupUpdateCheck !== false,
    closeToTray: src.closeToTray !== false,
    webServerPort: parsePort(src.webServerPort),
    webServerMode: normalizeServerMode(src.webServerMode),
    httpsEnabled: normalizeHttpsEnabled(src.httpsEnabled),
    tlsHostnames: normalizeTlsHostnames(src.tlsHostnames),
    allowedIpCidrs: normalizeAllowedIpCidrs(src.allowedIpCidrs),
    backup: {
      autoEnabled: backup.autoEnabled === true,
      intervalHours: clampInt(backup.intervalHours, 1, 24 * 30, base.backup.intervalHours),
      keepCount: clampInt(backup.keepCount, 1, 200, base.backup.keepCount),
      lastRunAt:
        typeof backup.lastRunAt === 'number' && Number.isFinite(backup.lastRunAt)
          ? backup.lastRunAt
          : null,
    },
  };
}

/** @type {AppSettings | null} */
let cache = null;

function load() {
  if (!cache) cache = normalizeSettings(readJsonSync(statePath(SETTINGS_FILE), {}));
  return cache;
}

/** Drops the cache after a backup restore replaced settings.json on disk. */
export function reloadSettings() {
  cache = null;
}

/** @returns {AppSettings} */
export function getSettings() {
  return structuredClone(load());
}

/** Sync accessor used by the HTTP guard on every request. */
export function getAllowedIpCidrs() {
  return load().allowedIpCidrs;
}

/** Fields safe to expose before login (theme + startup behaviour only). */
export function getPublicSettings() {
  const { accentColor, startupUpdateCheck } = load();
  return { accentColor, startupUpdateCheck };
}

/**
 * Shallow-merges `patch` (`backup` merges one level deeper) and persists.
 *
 * @param {Partial<AppSettings> & { backup?: Partial<BackupSettings> }} patch
 * @returns {Promise<AppSettings>}
 */
export function updateSettings(patch) {
  return withFileLock(statePath(SETTINGS_FILE), () => {
    const current = load();
    const next = normalizeSettings({
      ...current,
      ...patch,
      backup: { ...current.backup, ...(patch?.backup ?? {}) },
    });
    writeJsonSync(statePath(SETTINGS_FILE), next);
    cache = next;
    return structuredClone(next);
  });
}
