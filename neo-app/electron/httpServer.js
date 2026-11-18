import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { DEFAULT_PORT } from '../shared/constants.js';
import { parsePort } from '../shared/serverConfig.js';
import { ApiError, RawResponse, dispatchApi } from './api/registry.js';
import { getSettings } from './settingsService.js';

const MAX_BODY_BYTES = 256 * 1024 * 1024;
const LOCAL_HOST = '127.0.0.1';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8',
  '.wasm': 'application/wasm',
};

/**
 * @param {import('node:http').ServerResponse} res
 * @param {number} status
 * @param {unknown} payload
 */
function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(body);
}

/**
 * @param {import('node:http').IncomingMessage} req
 * @returns {Promise<any>}
 */
function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    /** @type {Buffer[]} */
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new ApiError('요청이 너무 큽니다.', 413));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (size === 0) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        reject(new ApiError('올바른 JSON 요청이 아닙니다.', 400));
      }
    });
    req.on('error', reject);
  });
}

/**
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
async function handleApiRequest(req, res) {
  try {
    if (req.method !== 'POST') throw new ApiError('POST 요청만 지원합니다.', 405);
    const name = decodeURIComponent((req.url ?? '').split('?')[0].slice('/api/'.length));
    // 로컬 전용: 로그인 없이 바로 사용한다.
    const user = {
      id: 'local',
      loginId: 'local',
      displayName: '로컬',
      role: 'super_admin',
    };
    const body = await readJsonBody(req);
    const windowId =
      String(req.headers['x-editor-window'] ?? '')
        .replace(/[^A-Za-z0-9_-]/g, '')
        .slice(0, 64) || 'main';

    const result = await dispatchApi(name, body, { user, token: '', clientIp: LOCAL_HOST, windowId });

    if (result instanceof RawResponse) {
      const headers = {
        'Content-Type': result.contentType,
        'Content-Length': result.buffer.length,
        'Cache-Control': 'no-store',
      };
      if (result.fileName) {
        headers['Content-Disposition'] = `attachment; filename*=UTF-8''${encodeURIComponent(result.fileName)}`;
      }
      res.writeHead(200, headers);
      res.end(result.buffer);
      return;
    }
    sendJson(res, 200, { ok: true, data: result ?? null });
  } catch (error) {
    if (error instanceof ApiError) {
      sendJson(res, error.status, { ok: false, error: error.message, ...error.extra });
      return;
    }
    console.error('[api] unexpected error:', error);
    sendJson(res, 500, {
      ok: false,
      error: error instanceof Error ? error.message : '서버 오류가 발생했습니다.',
    });
  }
}

/**
 * Serves the built renderer (production) with SPA fallback.
 *
 * @param {string} distDir
 * @returns {(req: import('node:http').IncomingMessage, res: import('node:http').ServerResponse) => void}
 */
function createStaticHandler(distDir) {
  const root = path.resolve(distDir);

  return (req, res) => {
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      res.writeHead(405).end();
      return;
    }

    let pathname = '/';
    try {
      pathname = decodeURIComponent((req.url ?? '/').split('?')[0]);
    } catch {
      res.writeHead(400).end();
      return;
    }

    let file = path.resolve(root, `.${pathname}`);
    if (file !== root && !file.startsWith(root + path.sep)) {
      res.writeHead(403).end();
      return;
    }
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      if (path.extname(pathname)) {
        res.writeHead(404).end('Not found');
        return;
      }
      file = path.join(root, 'index.html');
    }

    const ext = path.extname(file).toLowerCase();
    const isIndex = path.basename(file) === 'index.html';
    res.writeHead(200, {
      'Content-Type': MIME[ext] ?? 'application/octet-stream',
      'Cache-Control': isIndex
        ? 'no-cache'
        : pathname.startsWith('/assets/')
          ? 'public, max-age=31536000, immutable'
          : 'public, max-age=3600',
      'X-Content-Type-Options': 'nosniff',
    });
    if (req.method === 'HEAD') {
      res.end();
      return;
    }
    fs.createReadStream(file).pipe(res);
  };
}

/** @param {number} ms */
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * @param {import('node:http').Server} server
 * @param {string} host
 * @param {number} port
 * @param {number} [retries]
 */
async function listen(server, host, port, retries = 4) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await new Promise((resolve, reject) => {
        const onError = (err) => {
          server.off('listening', onListening);
          reject(err);
        };
        const onListening = () => {
          server.off('error', onError);
          resolve(undefined);
        };
        server.once('error', onError);
        server.once('listening', onListening);
        server.listen(port, host);
      });
      return;
    } catch (err) {
      if (err?.code !== 'EADDRINUSE' || attempt >= retries) throw err;
      await sleep(700 * (attempt + 1));
    }
  }
}

/**
 * Owns the one local HTTP server of the app (127.0.0.1 only).
 * Dev: Vite (HMR) in middleware mode on this same port; production: static files from `dist/`.
 *
 * @param {{
 *   isDev: boolean,
 *   projectRoot: string,
 *   distDir: string,
 *   env: { get: (key: string) => string | undefined },
 * }} options
 */
export function createServerManager({ isDev, projectRoot, distDir, env }) {
  /** @type {import('node:http').Server | null} */
  let server = null;
  /** @type {import('vite').ViteDevServer | null} */
  let vite = null;
  let running = false;
  /** @type {{ port: number, hostname: string }} */
  let current = { port: DEFAULT_PORT, hostname: LOCAL_HOST };
  /** @type {ReturnType<typeof createStaticHandler> | null} */
  let staticHandler = null;

  /** settings.json > env (APP_PORT) > default. Always binds 127.0.0.1. */
  function resolveConfig() {
    const settings = getSettings();
    const port = settings.webServerPort ?? parsePort(env.get('APP_PORT')) ?? DEFAULT_PORT;
    return { port, hostname: LOCAL_HOST };
  }

  /**
   * @param {import('node:http').IncomingMessage} req
   * @param {import('node:http').ServerResponse} res
   */
  async function handleRequest(req, res) {
    if ((req.url ?? '').startsWith('/api/')) {
      await handleApiRequest(req, res);
      return;
    }
    if (vite) {
      vite.middlewares(req, res);
      return;
    }
    staticHandler?.(req, res);
  }

  /** @param {{ port: number, hostname: string }} config */
  async function bringUp(config) {
    const next = http.createServer();
    next.on('request', (req, res) => {
      void handleRequest(req, res).catch((err) => {
        console.error('[http] request failed:', err);
        if (!res.headersSent) res.writeHead(500);
        res.end();
      });
    });

    if (isDev) {
      const { createServer: createViteServer } = await import('vite');
      vite = await createViteServer({
        configFile: path.join(projectRoot, 'vite.config.js'),
        server: { middlewareMode: true, hmr: { server: next }, allowedHosts: true },
        appType: 'spa',
      });
    } else {
      staticHandler ??= createStaticHandler(distDir);
    }

    try {
      await listen(next, config.hostname, config.port);
    } catch (err) {
      await vite?.close().catch(() => undefined);
      vite = null;
      throw err;
    }
    server = next;
    current = config;
    running = true;
    console.log(
      `[server] ${isDev ? 'dev (Vite HMR)' : 'production'} → http://${config.hostname}:${config.port}`,
    );
  }

  async function tearDown() {
    running = false;
    if (vite) {
      await vite.close().catch(() => undefined);
      vite = null;
    }
    const old = server;
    server = null;
    if (!old) return;
    const closed = new Promise((resolve) => old.close(() => resolve(undefined)));
    old.closeAllConnections();
    await Promise.race([closed, sleep(3000)]);
  }

  function info() {
    const settings = getSettings();
    const configured = resolveConfig();
    const scheme = 'http';
    return {
      running,
      port: current.port,
      hostname: current.hostname,
      mode: 'local',
      httpsEnabled: false,
      scheme,
      urls: [`${scheme}://${LOCAL_HOST}:${current.port}`],
      addresses: [],
      appUrl: `${scheme}://${LOCAL_HOST}:${current.port}`,
      configuredPort: configured.port,
      configuredMode: 'local',
      storedPort: settings.webServerPort,
      storedMode: 'local',
      isDev,
    };
  }

  return {
    info,

    async start() {
      if (running) return info();
      await bringUp(resolveConfig());
      return info();
    },

    async stop() {
      await tearDown();
    },
  };
}
