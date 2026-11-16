/**
 * Web server bind modes (서버 관리).
 *   local — 127.0.0.1 only (this PC)
 *   lan   — 0.0.0.0 (LAN / VPN clients can connect with a browser)
 *
 * @typedef {'local' | 'lan'} ServerMode
 */

export const SERVER_MODES = /** @type {const} */ (['local', 'lan']);

/** @param {unknown} value @returns {ServerMode | null} */
export function normalizeServerMode(value) {
  return value === 'local' || value === 'lan' ? value : null;
}

/** @param {ServerMode} mode */
export function hostnameForMode(mode) {
  return mode === 'lan' ? '0.0.0.0' : '127.0.0.1';
}

/** @param {string} hostname @returns {ServerMode} */
export function modeForHostname(hostname) {
  const host = String(hostname ?? '').trim().toLowerCase();
  return host === '127.0.0.1' || host === 'localhost' || host === '::1' ? 'local' : 'lan';
}

/** @param {unknown} value */
export function parsePort(value) {
  const port = Number.parseInt(String(value ?? '').trim(), 10);
  return Number.isInteger(port) && port >= 1024 && port <= 65535 ? port : null;
}
