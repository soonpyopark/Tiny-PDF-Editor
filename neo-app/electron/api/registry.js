/**
 * Tiny RPC registry. Every backend feature registers named handlers here;
 * the HTTP layer (electron/httpServer.js) exposes them as `POST /api/<name>`
 * and the renderer calls them with `api('<name>', body)` (src/lib/apiClient.js).
 *
 * Access levels (로컬 전용: 요청마다 local 슈퍼관리자 컨텍스트가 붙는다):
 *   public — 앱 정보 등
 *   user   — 일반 기능
 *   admin  — 환경설정
 *
 * @typedef {'public' | 'user' | 'admin'} ApiAccess
 *
 * @typedef {{
 *   user: { id: string, loginId: string, displayName: string, role: string } | null,
 *   token: string,
 *   clientIp: string,
 *   windowId?: string,
 * }} ApiContext
 *
 * @typedef {(body: any, ctx: ApiContext) => unknown | Promise<unknown>} ApiHandler
 */

import { AsyncLocalStorage } from 'node:async_hooks';

/** HTTP-aware error: the message is shown to the user as-is. */
export class ApiError extends Error {
  /**
   * @param {string} message
   * @param {number} [status]
   * @param {Record<string, unknown>} [extra]
   */
  constructor(message, status = 400, extra = {}) {
    super(message);
    this.status = status;
    this.extra = extra;
  }
}

/** Return this from a handler to send a file instead of JSON. */
export class RawResponse {
  /**
   * @param {Buffer} buffer
   * @param {{ fileName?: string, contentType?: string }} [options]
   */
  constructor(buffer, { fileName = '', contentType = 'application/octet-stream' } = {}) {
    this.buffer = buffer;
    this.fileName = fileName;
    this.contentType = contentType;
  }
}

/** @type {Map<string, { access: ApiAccess, handler: ApiHandler }>} */
const routes = new Map();

/**
 * Which editor window (document session) a request came from. The renderer
 * sends it in the `X-Editor-Window` header; handlers read it through
 * `currentWindowId()` so each window keeps its own PDF engine.
 */
const windowStore = new AsyncLocalStorage();

/** @returns {string} */
export function currentWindowId() {
  return windowStore.getStore() ?? 'main';
}

/**
 * @param {string} name e.g. `pdf.search`
 * @param {ApiAccess} access
 * @param {ApiHandler} handler
 */
export function defineApi(name, access, handler) {
  if (routes.has(name)) throw new Error(`API route registered twice: ${name}`);
  routes.set(name, { access, handler });
}

/**
 * @param {string} name
 * @param {any} body
 * @param {ApiContext} ctx
 */
export async function dispatchApi(name, body, ctx) {
  const route = routes.get(name);
  if (!route) throw new ApiError(`알 수 없는 요청입니다: ${name}`, 404);

  if (route.access !== 'public') {
    if (!ctx.user) throw new ApiError('요청을 처리할 수 없습니다.', 401);
    if (route.access === 'admin' && ctx.user.role !== 'super_admin') {
      throw new ApiError('이 요청을 사용할 수 없습니다.', 403);
    }
  }
  return windowStore.run(ctx.windowId || 'main', () => route.handler(body ?? {}, ctx));
}
