import { app, BrowserWindow, dialog, ipcMain, Menu, shell } from 'electron';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { APP_ID, APP_NAME } from './shared/constants.js';
import { registerCoreApi } from './electron/api/coreApi.js';
import { startBackupScheduler, stopBackupScheduler } from './electron/backupService.js';
import { setAppContext } from './electron/context.js';
import { createEnvReader } from './electron/envConfig.js';
import { createServerManager } from './electron/httpServer.js';
import { ensureBootstrapAdmin } from './electron/membersService.js';
import { registerModules } from './electron/modules/index.js';
import { disposeEngineSession } from './electron/modules/pdf.js';
import { runtime } from './electron/runtime.js';
import { createSplashWindow, registerSplashIpc, toggleAboutSplash } from './electron/splash.js';
import { isOwnServerCertificate } from './electron/tlsCerts.js';
import { createTrayController } from './electron/tray.js';
import { hideTitleBarIcon } from './electron/windowIcon.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// A closed console / pipe must never take the app down with EPIPE.
for (const stream of [process.stdout, process.stderr]) stream?.on?.('error', () => undefined);

const isDev = !app.isPackaged;

// Must run before any window / Jump List work so pinned taskbar icons keep the
// same identity (and icon) after reboot. Matches MSI ShortcutProperty AUMID.
if (process.platform === 'win32') {
  app.setAppUserModelId(APP_ID);
}

/* -------------------------------------------------------------------------- */
/* state folder                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Where settings / members / backups live:
 *   - APP_DATA_DIR env override
 *   - dev            → <project>/data
 *   - portable zip   → <exe folder>/data   (marker file `.portable` beside the exe)
 *   - installed (MSI / dmg) → <userData>/data
 */
function resolveStorage() {
  const override = String(process.env.APP_DATA_DIR ?? '').trim();
  const exeDir = path.dirname(app.getPath('exe'));
  const portable = !isDev && fs.existsSync(path.join(exeDir, '.portable'));

  if (isDev) {
    // Own userData so a dev run never fights an installed copy for the instance lock.
    app.setPath('userData', path.join(__dirname, '.dev-userdata'));
  } else if (portable) {
    app.setPath('userData', path.join(exeDir, 'data-cache'));
  }

  const stateRoot = override
    ? path.resolve(override)
    : isDev
      ? path.join(__dirname, 'data')
      : portable
        ? path.join(exeDir, 'data')
        : path.join(app.getPath('userData'), 'data');

  return { stateRoot, portable, exeDir };
}

const storage = resolveStorage();

/* -------------------------------------------------------------------------- */
/* single instance                                                            */
/* -------------------------------------------------------------------------- */

/** @type {BrowserWindow | null} */
let mainWindow = null;
let isQuitting = false;
/** @type {ReturnType<typeof createServerManager> | null} */
let serverManager = null;
/** @type {ReturnType<typeof createTrayController> | null} */
let trayController = null;
/** 시작 스플래시 (메인 창이 준비되면 닫는다). */
/** @type {ReturnType<typeof createSplashWindow> | null} */
let splash = null;
/** 문서 창이 같은 앱 서버를 가리키도록 기본 주소를 기억한다. */
let appUrlBase = '';

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.whenReady().then(() => {
    dialog.showMessageBoxSync({
      type: 'info',
      title: APP_NAME,
      message: '프로그램이 이미 실행 중입니다.',
      buttons: ['확인'],
    });
    app.exit(0);
  });
} else {
  app.on('second-instance', focusMainWindow);
  app.whenReady().then(boot).catch(fatal);
}

function focusMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

/** @param {unknown} error */
function fatal(error) {
  const message = error instanceof Error ? error.message : String(error);
  console.error('[fatal]', error);
  splash?.close();
  splash = null;
  dialog.showErrorBox(`${APP_NAME} 시작 실패`, message);
  app.exit(1);
}

/* -------------------------------------------------------------------------- */
/* boot                                                                       */
/* -------------------------------------------------------------------------- */

async function boot() {
  splash = createSplashWindow({ iconPath: resolveIconPath() });
  fs.mkdirSync(storage.stateRoot, { recursive: true });

  setAppContext({
    isDev,
    projectRoot: __dirname,
    distDir: path.join(__dirname, 'dist'),
    stateRoot: storage.stateRoot,
    portable: storage.portable,
  });
  runtime.stateRoot = storage.stateRoot;
  runtime.portable = storage.portable;
  runtime.autoLaunch = {
    supported: !isDev,
    get: () => app.getLoginItemSettings().openAtLogin,
    set: (enabled) => app.setLoginItemSettings({ openAtLogin: Boolean(enabled) }),
  };

  await ensureBootstrapAdmin();
  registerCoreApi();
  registerModules();

  serverManager = createServerManager({
    isDev,
    projectRoot: __dirname,
    distDir: path.join(__dirname, 'dist'),
    env: createEnvReader([storage.exeDir, storage.stateRoot, ...(isDev ? [__dirname] : [])]),
  });
  runtime.server = serverManager;

  let info;
  try {
    info = await serverManager.start();
  } catch (err) {
    if (err?.code === 'EADDRINUSE') {
      throw new Error(
        '서버 포트가 이미 사용 중입니다.\n다른 프로그램을 종료하거나 data/settings.json 의 webServerPort 를 바꿔 주세요.',
      );
    }
    throw err;
  }

  setupMenu();
  registerIpc();
  appUrlBase = info.appUrl;
  createMainWindow(info.appUrl);
  trayController = createTrayController({
    resolveIconPath,
    getMainWindow: () => mainWindow,
    focusMainWindow,
    quitApp: quitFromTray,
  });
  trayController.create();
  startBackupScheduler();

  app.on('activate', () => {
    focusMainWindow();
  });
}

/* -------------------------------------------------------------------------- */
/* window                                                                     */
/* -------------------------------------------------------------------------- */

function resolveIconPath() {
  const candidates = [
    path.join(__dirname, 'build', 'icon.png'),
    path.join(process.resourcesPath ?? '', 'icon.png'),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate));
}

/** @param {string} url */
function isAppUrl(url) {
  try {
    const parsed = new URL(url);
    const info = serverManager?.info();
    return /^https?:$/.test(parsed.protocol) && Number(parsed.port) === info?.port;
  } catch {
    return false;
  }
}

/** @param {string} url */
function openExternalSafe(url) {
  if (/^(https?:|mailto:)/i.test(url)) void shell.openExternal(url);
}

/** @param {string} appUrl */
function createMainWindow(appUrl) {
  mainWindow = createAppWindow(appUrl, { main: true, windowId: 'main' });
}

/**
 * 보기 > 새 창으로 열기: 같은 앱을 가리키는 새 창을 만든다.
 * 그 창은 자기 PDF 엔진 세션을 쓰므로 문서가 섞이지 않는다.
 * @param {string} filePath
 */
function openDocumentWindow(filePath) {
  if (!appUrlBase) return false;
  const windowId = randomUUID().replace(/-/g, '');
  const url = new URL(appUrlBase);
  url.searchParams.set('win', windowId);
  if (filePath) url.searchParams.set('open', filePath);
  createAppWindow(url.toString(), { main: false, windowId });
  return true;
}

/**
 * @param {string} appUrl
 * @param {{ main: boolean, windowId: string }} options
 * @returns {BrowserWindow}
 */
function createAppWindow(appUrl, { main, windowId }) {
  const icon = resolveIconPath();

  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    title: APP_NAME,
    backgroundColor: '#0f172a',
    autoHideMenuBar: true,
    show: false,
    ...(icon ? { icon } : {}),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // The title-bar icon can only be removed from a window that is already shown
  // (Windows re-applies the icon on first show), so show it invisibly, drop the
  // icon, then fade it in — no flash of the icon.
  win.once('ready-to-show', () => {
    win.setOpacity(0);
    win.show();
    if (main && splash) {
      // 메인 창이 뜨면 최소 표시 시간(700ms)을 채운 뒤 스플래시를 닫는다.
      splash.closeWhenReady();
      splash = null;
    }
    void hideTitleBarIcon(win).finally(() => {
      if (!win.isDestroyed()) win.setOpacity(1);
    });
  });
  win.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
    if (!isMainFrame) return;
    console.error(`[window] load failed: ${description} (${code}) ${url}`);
    // The server may still be rebinding (port change) — try once more.
    setTimeout(() => {
      if (!win.isDestroyed()) void win.loadURL(url || appUrl);
    }, 800);
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternalSafe(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return;
    // Port changes in 서버 관리 navigate to the new port of this same server.
    if (/^https?:\/\/(127\.0\.0\.1|localhost):\d+/i.test(url)) return;
    event.preventDefault();
    openExternalSafe(url);
  });

  win.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown') return;
    const ctrl = input.control || input.meta;
    if (input.key === 'F5' || (ctrl && input.key.toLowerCase() === 'r')) {
      win.webContents.reload();
      event.preventDefault();
    } else if (isDev && (input.key === 'F12' || (ctrl && input.shift && input.key.toLowerCase() === 'i'))) {
      win.webContents.toggleDevTools();
      event.preventDefault();
    }
  });

  // X closes → hide to tray (Exit in the tray menu actually quits).
  // 문서 창은 실제로 닫히고, 그때 자기 엔진 세션을 끈다.
  win.on('close', (event) => {
    if (main && !isQuitting) {
      event.preventDefault();
      win.hide();
    }
  });

  win.on('closed', () => {
    if (main) mainWindow = null;
    else disposeEngineSession(windowId);
  });

  void win.loadURL(appUrl);
  return win;
}

function quitFromTray() {
  isQuitting = true;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.removeAllListeners('close');
    mainWindow.close();
  }
  app.quit();
}

function setupMenu() {
  if (process.platform === 'darwin') {
    // macOS needs an Edit menu or Cmd+C / Cmd+V stop working.
    Menu.setApplicationMenu(
      Menu.buildFromTemplate([
        { role: 'appMenu' },
        { role: 'editMenu' },
        { role: 'windowMenu' },
      ]),
    );
  } else {
    Menu.setApplicationMenu(null);
  }
}

/* -------------------------------------------------------------------------- */
/* HTTPS: trust the certificate this app issued for itself                    */
/* -------------------------------------------------------------------------- */

// The window talks to our own server, whose certificate is signed by a local CA
// that is not installed in the OS. Accept exactly that certificate and nothing else.
app.on('certificate-error', (event, _webContents, url, _error, certificate, callback) => {
  let trusted = false;
  try {
    const { hostname } = new URL(url);
    trusted = (hostname === '127.0.0.1' || hostname === 'localhost') && isOwnServerCertificate(certificate);
  } catch {
    trusted = false;
  }
  if (!trusted) return callback(false);
  event.preventDefault();
  callback(true);
});

/* -------------------------------------------------------------------------- */
/* IPC (Electron window only — browsers on the LAN never see these)           */
/* -------------------------------------------------------------------------- */

function registerIpc() {
  ipcMain.handle('frame:getInfo', () => ({
    platform: process.platform,
    arch: process.arch,
    stateRoot: storage.stateRoot,
    portable: storage.portable,
    isDev,
  }));

  ipcMain.handle('frame:openExternal', (_event, url) => {
    openExternalSafe(String(url ?? ''));
  });

  /** Reveals the state folder (or a sub-folder of it) in the OS file manager. */
  ipcMain.handle('frame:openStateFolder', async (_event, sub = '') => {
    const root = path.resolve(storage.stateRoot);
    const target = path.resolve(root, String(sub ?? ''));
    if (target !== root && !target.startsWith(root + path.sep)) return false;
    fs.mkdirSync(target, { recursive: true });
    return (await shell.openPath(target)) === '';
  });

  ipcMain.handle('frame:quit', () => {
    quitFromTray();
  });

  /** 도움말 > 정보: 스플래시 형태의 정보 창을 토글한다. */
  ipcMain.handle('frame:showAboutSplash', () => toggleAboutSplash({ iconPath: resolveIconPath() }));
  registerSplashIpc();

  /** 보기 > 새 창으로 열기: 파일 경로를 가진 새 문서 창을 연다. */
  ipcMain.handle('frame:openDocumentWindow', (_event, filePath) =>
    openDocumentWindow(String(filePath ?? '').trim()),
  );
}

/* -------------------------------------------------------------------------- */
/* shutdown                                                                   */
/* -------------------------------------------------------------------------- */

app.on('window-all-closed', () => {
  // Main window hides to tray — keep the app and server running.
});

let quitCleanupStarted = false;

app.on('before-quit', (event) => {
  isQuitting = true;
  if (quitCleanupStarted) return;
  quitCleanupStarted = true;

  stopBackupScheduler();
  trayController?.destroy();
  trayController = null;
  if (!serverManager) return;

  // Release the port before the process exits.
  event.preventDefault();
  void serverManager
    .stop()
    .catch((err) => console.warn('[server] stop failed:', err))
    .finally(() => app.exit(0));
});
