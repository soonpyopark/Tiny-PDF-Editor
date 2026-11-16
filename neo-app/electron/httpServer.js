import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import path from 'node:path';
import { APP_FILE_NAME, DEFAULT_PORT } from '../shared/constants.js';
import { httpScheme, normalizeHttpsEnabled, normalizeTlsHostnames } from '../shared/httpsConfig.js';
import {
  hostnameForMode,
  modeForHostname,
  normalizeServerMode,
  parsePort,
} from '../shared/serverConfig.js';
import { ApiError, RawResponse, dispatchApi } from './api/registry.js';
import { getSessionUser } from './authService.js';
import { getClientIpFromRequest, ipBlockedHtml, isIpAllowed } from './ipAllowlist.js';
import { getLocalIPv4Addresses } from './networkInfo.js';
import { getAllowedIpCidrs, getSettings, updateSettings } from './settingsService.js';
import { ensureTlsMaterial, readCaPem } from './tlsCerts.js';

const MAX_BODY_BYTES = 256 * 1024 * 1024;

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
 * @param {string} clientIp
 */
async function handleApiRequest(req, res, clientIp) {
  try {
    if (req.method !== 'POST') throw new ApiError('POST 요청만 지원합니다.', 405);
    const name = decodeURIComponent((req.url ?? '').split('?')[0].slice('/api/'.length));
    const authHeader = String(req.headers.authorization ?? '');
    const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7).trim() : '';
    // Local-only app: open the editor without a login session.
    const user = getSessionUser(token) ?? {
      id: 'local',
      loginId: 'local',
      displayName: '로컬',
      role: 'super_admin',
    };
    const body = await readJsonBody(req);
    // 창마다 독립된 PDF 엔진을 쓰기 위한 식별자 (없으면 기본 창).
    const windowId =
      String(req.headers['x-editor-window'] ?? '')
        .replace(/[^A-Za-z0-9_-]/g, '')
        .slice(0, 64) || 'main';

    const result = await dispatchApi(name, body, { user, token, clientIp, windowId });

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
      // Real asset requests 404; anything else is a client-side route.
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
 * @param {number} [retries] EADDRINUSE retries (the old process may still be exiting)
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
 * Checks that nothing else holds `port` on `host`.
 * @param {string} host
 * @param {number} port
 */
function probePort(host, port) {
  return new Promise((resolve) => {
    const tester = net.createServer();
    tester.once('error', () => resolve(false));
    tester.once('listening', () => tester.close(() => resolve(true)));
    tester.listen(port, host);
  });
}

/**
 * Owns the one web server of the app (HTTP, or HTTPS when enabled in 서버 관리).
 * Dev: Vite (HMR) in middleware mode on this same port; production: static
 * files from `dist/`. Any config change tears the server down and brings a
 * fresh one up, because http / https are different server classes.
 *
 * @param {{
 *   isDev: boolean,
 *   projectRoot: string,
 *   distDir: string,
 *   env: { get: (key: string) => string | undefined },
 * }} options
 */
export function createServerManager({ isDev, projectRoot, distDir, env }) {
  /** @type {import('node:http').Server | import('node:https').Server | null} */
  let server = null;
  /** @type {import('vite').ViteDevServer | null} */
  let vite = null;
  let running = false;
  /** @type {{ port: number, hostname: string, httpsEnabled: boolean }} */
  let current = { port: DEFAULT_PORT, hostname: hostnameForMode('local'), httpsEnabled: false };
  /** @type {ReturnType<typeof createStaticHandler> | null} */
  let staticHandler = null;

  /** settings.json > env (APP_PORT / APP_HOST) > defaults (local only, HTTP). */
  function resolveConfig() {
    const settings = getSettings();
    const port = settings.webServerPort ?? parsePort(env.get('APP_PORT')) ?? DEFAULT_PORT;
    const envHost = String(env.get('APP_HOST') ?? '').trim();
    const mode =
      settings.webServerMode ?? (envHost ? modeForHostname(envHost) : /** @type {const} */ ('local'));
    return { port, hostname: hostnameForMode(mode), httpsEnabled: settings.httpsEnabled };
  }

  /**
   * @param {import('node:http').IncomingMessage} req
   * @param {import('node:http').ServerResponse} res
   */
  async function handleRequest(req, res) {
    const clientIp = getClientIpFromRequest(req);
    const isApi = (req.url ?? '').startsWith('/api/');

    if (!isIpAllowed(clientIp, getAllowedIpCidrs())) {
      if (isApi) {
        sendJson(res, 403, { ok: false, error: '허용되지 않은 IP 입니다.' });
      } else {
        res.writeHead(403, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(ipBlockedHtml(clientIp));
      }
      return;
    }

    if (isApi) {
      await handleApiRequest(req, res, clientIp);
      return;
    }

    // The CA certificate is public: other devices fetch it to trust the HTTPS server.
    if (req.method === 'GET' && (req.url ?? '').split('?')[0] === '/ca.crt') {
      const pem = readCaPem();
      if (pem) {
        res.writeHead(200, {
          'Content-Type': 'application/x-x509-ca-cert',
          'Content-Disposition': `attachment; filename="${APP_FILE_NAME}-ca.crt"`,
          'Cache-Control': 'no-store',
        });
        res.end(pem);
        return;
      }
    }

    if (vite) {
      vite.middlewares(req, res);
      return;
    }
    staticHandler?.(req, res);
  }

  /** @param {import('node:http').IncomingMessage} req @param {import('node:stream').Duplex} socket */
  function handleUpgrade(req, socket) {
    // Reject websocket upgrades from blocked IPs (Vite HMR in dev).
    if (!isIpAllowed(getClientIpFromRequest(req), getAllowedIpCidrs())) {
      socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
      socket.destroy();
    }
  }

  /** @param {{ port: number, hostname: string, httpsEnabled: boolean }} config */
  async function bringUp(config) {
    let next;
    if (config.httpsEnabled) {
      const tls = await ensureTlsMaterial();
      next = https.createServer({ key: tls.key, cert: `${tls.cert.trim()}\n${tls.ca.trim()}\n` });
    } else {
      next = http.createServer();
    }
    next.on('request', (req, res) => {
      void handleRequest(req, res).catch((err) => {
        console.error('[http] request failed:', err);
        if (!res.headersSent) res.writeHead(500);
        res.end();
      });
    });
    next.on('upgrade', handleUpgrade);
    // A browser refusing the certificate is routine, not an error worth a stack trace.
    next.on('tlsClientError', () => undefined);

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
      `[server] ${isDev ? 'dev (Vite HMR)' : 'production'} → ${httpScheme(config.httpsEnabled)}://${config.hostname}:${config.port}`,
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
    const mode = modeForHostname(current.hostname);
    const settings = getSettings();
    const configured = resolveConfig();
    const scheme = httpScheme(current.httpsEnabled);
    const urls = [`${scheme}://127.0.0.1:${current.port}`];
    if (mode === 'lan') {
      for (const address of getLocalIPv4Addresses()) urls.push(`${scheme}://${address}:${current.port}`);
    }
    return {
      running,
      port: current.port,
      hostname: current.hostname,
      mode,
      httpsEnabled: current.httpsEnabled,
      scheme,
      urls,
      addresses: getLocalIPv4Addresses(),
      appUrl: `${scheme}://127.0.0.1:${current.port}`,
      configuredPort: configured.port,
      configuredMode: modeForHostname(configured.hostname),
      storedPort: settings.webServerPort,
      storedMode: settings.webServerMode,
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

    /**
     * Validates, persists and (shortly after the HTTP response flushed)
     * restarts the server. The renderer must navigate to the new URL.
     *
     * @param {{
     *   port: unknown,
     *   mode: unknown,
     *   httpsEnabled?: unknown,
     *   tlsHostnames?: unknown,
     *   regenerateTls?: boolean,
     * }} request
     */
    async applyConfig(request) {
      const port = parsePort(request?.port);
      const mode = normalizeServerMode(request?.mode);
      if (!port) throw new ApiError('포트는 1024~65535 사이 숫자여야 합니다.');
      if (!mode) throw new ApiError('접속 허용 범위가 올바르지 않습니다.');

      const httpsEnabled =
        request?.httpsEnabled === undefined
          ? current.httpsEnabled
          : normalizeHttpsEnabled(request.httpsEnabled);
      const next = { port, hostname: hostnameForMode(mode), httpsEnabled };
      const changed =
        next.port !== current.port ||
        next.hostname !== current.hostname ||
        next.httpsEnabled !== current.httpsEnabled;

      if (next.port !== current.port && !(await probePort(next.hostname, next.port))) {
        throw new ApiError(`포트 ${port} 는 이미 다른 프로그램이 사용 중입니다.`);
      }

      const before = getSettings();
      /** @type {Record<string, unknown>} */
      const patch = { webServerPort: port, webServerMode: mode, httpsEnabled };
      let hostsChanged = false;
      if (request?.tlsHostnames !== undefined) {
        const hosts = normalizeTlsHostnames(request.tlsHostnames);
        hostsChanged = hosts.join(',') !== before.tlsHostnames.join(',');
        patch.tlsHostnames = hosts;
      }
      await updateSettings(patch);

      // Issue / refresh certificates now so a failure is reported to the user,
      // instead of surfacing as a server that silently fails to come back up.
      let certRenewed = false;
      if (httpsEnabled || hostsChanged || request?.regenerateTls) {
        try {
          certRenewed = (await ensureTlsMaterial({ force: Boolean(request?.regenerateTls) })).regenerated;
        } catch (err) {
          await updateSettings({
            webServerPort: before.webServerPort,
            webServerMode: before.webServerMode,
            httpsEnabled: before.httpsEnabled,
            tlsHostnames: before.tlsHostnames,
          });
          throw new ApiError(
            `인증서를 만들지 못했습니다: ${err instanceof Error ? err.message : String(err)}`,
            500,
          );
        }
      }

      const restart = changed || (current.httpsEnabled && httpsEnabled && certRenewed);
      const scheme = httpScheme(httpsEnabled);
      if (!restart) return { ...info(), restarting: false, certRenewed };

      const previous = { ...current };
      setTimeout(() => {
        void (async () => {
          try {
            await tearDown();
            await bringUp(next);
          } catch (err) {
            console.error('[server] restart failed, restoring previous settings:', err);
            await updateSettings({
              webServerPort: previous.port,
              webServerMode: modeForHostname(previous.hostname),
              httpsEnabled: previous.httpsEnabled,
            }).catch(() => undefined);
            await tearDown().catch(() => undefined);
            await bringUp(previous).catch((e) => console.error('[server] restore failed:', e));
          }
        })();
      }, 400);

      return {
        ...info(),
        port: next.port,
        mode,
        httpsEnabled,
        scheme,
        appUrl: `${scheme}://127.0.0.1:${next.port}`,
        restarting: true,
        certRenewed,
      };
    },
  };
}
