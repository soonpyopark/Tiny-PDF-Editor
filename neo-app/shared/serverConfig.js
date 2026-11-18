/**
 * Local web server helpers (127.0.0.1 only).
 */

/** @param {unknown} value */
export function parsePort(value) {
  const port = Number.parseInt(String(value ?? '').trim(), 10);
  return Number.isInteger(port) && port >= 1024 && port <= 65535 ? port : null;
}
