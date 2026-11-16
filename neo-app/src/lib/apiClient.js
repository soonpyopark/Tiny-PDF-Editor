/**
 * Thin client for the backend RPC (electron/api/registry.js).
 *
 *   const { members } = await api('members.list');
 *   const blob = await apiDownload('backup.download', { fileName });
 *
 * The bearer token lives in localStorage ("로그인 유지") or sessionStorage.
 */

const TOKEN_KEY = 'frame.token';

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
  const key = String(tab || '').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 16);
  return key ? `${base}__${key}` : base;
}

export function getToken() {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY) || window.localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

/**
 * @param {string} token
 * @param {boolean} remember persist across app restarts
 */
export function setToken(token, remember) {
  clearToken();
  try {
    (remember ? window.localStorage : window.sessionStorage).setItem(TOKEN_KEY, token);
  } catch {
    // storage unavailable: session works until reload
  }
}

export function clearToken() {
  try {
    window.sessionStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

/** Fired when the server says the token is no longer valid. */
export const UNAUTHORIZED_EVENT = 'frame:unauthorized';

/**
 * @param {string} name
 * @param {unknown} body
 */
async function request(name, body, tab = '') {
  const token = getToken();
  let response;
  try {
    response = await fetch(`/api/${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Editor-Window': engineScope(tab),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
 * @param {string} name
 */
async function failure(response, name) {
  /** @type {any} */
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    // non-JSON error body
  }
  if (response.status === 401 && name !== 'auth.login') {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  return new ApiRequestError(payload?.error || `요청에 실패했습니다. (HTTP ${response.status})`, response.status, payload);
}

/**
 * @template [T=any]
 * @param {string} name
 * @param {unknown} [body]
 * @returns {Promise<T>}
 */
export async function api(name, body = {}, options = {}) {
  const response = await request(name, body, options?.tab ?? '');
  if (!response.ok) throw await failure(response, name);
  const payload = await response.json();
  return payload?.data;
}

/**
 * @param {string} name
 * @param {unknown} [body]
 * @returns {Promise<Blob>}
 */
export async function apiDownload(name, body = {}) {
  const response = await request(name, body);
  if (!response.ok) throw await failure(response, name);
  return response.blob();
}

/** @param {Blob} blob @param {string} fileName */
export function saveBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Native bridge exposed by preload.cjs; undefined in a plain browser. */
export function getNative() {
  return typeof window !== 'undefined' ? window.frame : undefined;
}
