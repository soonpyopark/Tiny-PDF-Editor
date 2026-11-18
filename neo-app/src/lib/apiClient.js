/**
 * Thin client for the backend RPC (electron/api/registry.js).
 *
 *   const status = await api('pdf.status');
 */

/**
 * 창 식별자. 문서 창은 `?win=<id>` 로 열리고, 기본(main) 창은 값이 없다.
 * 같은 창 안의 모든 요청이 같은 PDF 엔진 세션을 쓰도록 한다.
 */
export function getWindowId() {
  try {
    const raw = new URLSearchParams(window.location.search).get('win') || '';
    return raw.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64) || 'main';
  } catch {
    return 'main';
  }
}

/**
 * 탭 식별자 포함 엔진 세션 키. 탭이 없으면(첫 탭) 창 식별자와 같다.
 * 탭마다 PDF 엔진 세션이 따로 생기므로 `창__탭` 형식으로 만든다.
 * @param {string} [tab]
 */
export function engineScope(tab = '') {
  const base = getWindowId();
  const key = String(tab || '')
    .replace(/[^A-Za-z0-9_-]/g, '')
    .slice(0, 16);
  return key ? `${base}__${key}` : base;
}

export class ApiRequestError extends Error {
  /**
   * @param {string} message
   * @param {number} status
   * @param {Record<string, unknown>} [data]
   */
  constructor(message, status, data = {}) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

/**
 * @param {string} name
 * @param {unknown} body
 * @param {string} [tab]
 */
async function request(name, body, tab = '') {
  let response;
  try {
    response = await fetch(`/api/${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Editor-Window': engineScope(tab),
      },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw new ApiRequestError('서버에 연결할 수 없습니다.', 0);
  }
  return response;
}

/**
 * @param {Response} response
 */
async function failure(response) {
  /** @type {any} */
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    // non-JSON error body
  }
  return new ApiRequestError(
    payload?.error || `요청에 실패했습니다. (HTTP ${response.status})`,
    response.status,
    payload,
  );
}

/**
 * @template [T=any]
 * @param {string} name
 * @param {unknown} [body]
 * @param {{ tab?: string }} [options]
 * @returns {Promise<T>}
 */
export async function api(name, body = {}, options = {}) {
  const response = await request(name, body, options?.tab ?? '');
  if (!response.ok) throw await failure(response);
  /** @type {any} */
  const payload = await response.json();
  return payload.data;
}

/**
 * @param {string} name
 * @param {unknown} [body]
 * @param {{ tab?: string }} [options]
 */
export async function apiDownload(name, body = {}, options = {}) {
  const response = await request(name, body, options?.tab ?? '');
  if (!response.ok) throw await failure(response);
  return response.blob();
}

/** @returns {import('../../electron/preload.cjs') | null} */
export function getNative() {
  return window.tinyNative ?? null;
}
