/**
 * HTTPS settings shared by the server (electron/) and the settings screen (src/).
 */

/** @param {unknown} value @returns {boolean} */
export function normalizeHttpsEnabled(value) {
  return value === true || value === 1 || value === '1' || value === 'true';
}

/** @param {boolean} httpsEnabled */
export function httpScheme(httpsEnabled) {
  return httpsEnabled ? 'https' : 'http';
}

/**
 * @param {string} host
 * @param {number} port
 * @param {boolean} httpsEnabled
 */
export function formatAccessUrl(host, port, httpsEnabled) {
  return `${httpScheme(httpsEnabled)}://${host}:${port}`;
}

/** @param {string} value */
function isIpv4Host(value) {
  return /^\d{1,3}(?:\.\d{1,3}){3}$/.test(value);
}

/**
 * Strips scheme / port / path from a pasted URL. Accepts DNS names and IPv4.
 *
 * @param {unknown} value
 * @returns {string} '' when the value is not a usable host name
 */
export function normalizeTlsHostname(value) {
  let raw = String(value ?? '').trim().toLowerCase();
  if (!raw) return '';
  raw = raw.replace(/^https?:\/\//, '');
  raw = raw.split('/')[0] ?? '';
  raw = raw.replace(/:\d+$/, '');
  if (raw.startsWith('[') && raw.endsWith(']')) raw = raw.slice(1, -1);
  if (isIpv4Host(raw)) return raw;
  const dnsName = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;
  if (!dnsName.test(raw) && raw !== 'localhost') return '';
  return raw;
}

/**
 * @param {unknown} value array, or text separated by whitespace / comma / semicolon
 * @returns {string[]} unique, valid host names
 */
export function normalizeTlsHostnames(value) {
  const parts = Array.isArray(value) ? value : String(value ?? '').split(/[\s,;]+/);
  const out = [];
  const seen = new Set();
  for (const part of parts) {
    const host = normalizeTlsHostname(part);
    if (!host || seen.has(host)) continue;
    seen.add(host);
    out.push(host);
  }
  return out;
}
