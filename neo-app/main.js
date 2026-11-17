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
import {
  WATCH_FLAG,
  ensurePrintService,
  handOffToLightWatcher,
  keepWatchAfterQuit,
  pathsFromArgv,
  watchInProcess,
} from './electron/printService.js';
import { runtime } from './electron/runtime.js';
import { getSettings } from './electron/settingsService.js';
import { createSplashWindow, registerSplashIpc, toggleAboutSplash } from './electron/splash.js';
import { isOwnServerCertificate } from './electron/tlsCerts.js';
import { createTrayController } from './electron/tray.js';
import { hideTitleBarIcon } from './electron/windowIcon.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// A closed console / pipe must never take the app down with EPIPE.
for (const stream of [process.stdout, process.stderr]) stream?.on?.('error', () => undefined);

const isDev = !app.isPackaged;

// 테스트·진단 전용: 원격 디버깅 포트를 연다. 평소에는 설정하지 않는다.
if (process.env.TINY_DEBUG_PORT) {
  app.commandLine.appendSwitch('remote-debugging-port', String(process.env.TINY_DEBUG_PORT));
}

// 메모리 절약 (배포본 측정, 문서 1개 연 상태): Electron 쪽 개인 메모리 222MB → 141MB.
//  - GPU 프로세스(97MB)를 소프트웨어 렌더링으로 돌린다. 화면은 DOM + PDF 쪽 이미지뿐이라 GPU 가속이 필요 없다.
//    문제가 생기면 TINY_ENABLE_GPU=1 로 실행해 예전처럼 GPU 가속을 켠다.
//  - 네트워크 서비스를 main 프로세스 안에서 돌려 보조 프로세스 하나를 줄인다.
// 두 스위치 모두 app ready 전에 설정해야 한다.
if (process.env.TINY_ENABLE_GPU !== '1') {
  app.commandLine.appendSwitch('disable-gpu');
}
app.commandLine.appendSwitch('enable-features', 'NetworkServiceInProcess2');

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
/** 저장 여부 확인이 끝나 메인 창을 실제로 닫아도 되는지. */
let mainCloseApproved = false;
/** 저장 여부 확인 중인 요청 종류: 'hide'(X 버튼) 또는 'quit'(종료). 없으면 null. */
/** @type {'hide' | 'quit' | null} */
let closeReason = null;
/** 열려 있는 문서 창(새 창으로 연 창). 닫기·종료 때 저장 여부를 묻는다. */
const documentWindows = new Set();
/** 저장 여부 확인이 끝나 한 번 닫아도 되는 문서 창. 닫히면서 소비된다. */
const closeApprovedDocWindows = new WeakSet();
/** 문서 창별 저장 여부 응답 대기. key = webContents.id, value = resolve(proceed) */
/** @type {Map<number, (proceed: boolean) => void>} */
const pendingDocCloseWaiters = new Map();
/** 문서 창 저장 여부 확인이 모두 끝나 실제 종료를 진행해도 되는지. */
let quitDocumentsConfirmed = false;
let quitDocumentsConfirming = false;
/** @type {ReturnType<typeof createServerManager> | null} */
let serverManager = null;
/** @type {ReturnType<typeof createTrayController> | null} */
let trayController = null;
/** 시작 스플래시 (메인 창이 준비되면 닫는다). */
/** @type {ReturnType<typeof createSplashWindow> | null} */
let splash = null;
/** 문서 창이 같은 앱 서버를 가리키도록 기본 주소를 기억한다. */
let appUrlBase = '';

/**
 * `<앱> --print-watch` — 로그인 Run 키가 띄우는 모드. 창도 단일 인스턴스 락도 쓰지 않는다.
 * 인쇄 감시는 가벼운 Node 프로세스(print-watch.mjs)가 맡고, 이 프로세스는 곧바로 끝난다.
 */
const printWatchMode = process.argv.includes(WATCH_FLAG);

const gotLock = printWatchMode ? true : app.requestSingleInstanceLock();
if (printWatchMode) {
  app.whenReady().then(runPrintWatchMode).catch(() => app.exit(1));
} else if (!gotLock) {
  // 이미 실행 중인 앱이 second-instance 로 이 프로세스의 인자(열 파일 경로)를 받는다.
  // 인쇄·파일 열기 때마다 뜨는 일이므로 대화상자 없이 조용히 끝낸다.
  app.exit(0);
} else {
  app.on('second-instance', (_event, argv, workingDirectory) => {
    focusMainWindow();
    deliverExternalPaths(pathsFromArgv(argv, workingDirectory));
  });
  // macOS: Finder/Dock 으로 파일을 열면 open-file 이 온다.
  app.on('open-file', (event, filePath) => {
    event.preventDefault();
    deliverExternalPaths([filePath]);
  });
  app.whenReady().then(boot).catch(fatal);
}

function runPrintWatchMode() {
  if (handOffToLightWatcher()) {
    app.exit(0);
    return;
  }
  // 가벼운 감시자를 못 띄우면 이 프로세스가 직접 감시한다 (인쇄 경로를 포기하지 않는다).
  watchInProcess();
}

function focusMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

/* -------------------------------------------------------------------------- */
/* 외부에서 넘어온 파일 (인쇄 PDF, 더블클릭/연결 프로그램, 명령줄)           */
/* -------------------------------------------------------------------------- */

/** 렌더러가 받을 준비가 되기 전에 온 경로를 잠시 쌓아 둔다. */
/** @type {string[]} */
const pendingOpenPaths = [];
/** 메인 창 렌더러가 frame:openPaths 를 받을 준비가 됐는지. */
let rendererOpenReady = false;

/** @param {string[]} paths */
function deliverExternalPaths(paths) {
  const list = paths.filter((item) => typeof item === 'string' && item);
  if (!list.length) return;
  console.log('[open] external paths:', list.join(' | '));
  pendingOpenPaths.push(...list);
  flushOpenPaths();
}

function flushOpenPaths() {
  if (!rendererOpenReady || !mainWindow || mainWindow.isDestroyed()) return;
  const batch = pendingOpenPaths.splice(0);
  if (batch.length) mainWindow.webContents.send('frame:openPaths', batch);
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
  // 시작 인자(인쇄 PDF, 연결 프로그램으로 연 파일)의 첫 경로는 창 주소로, 나머지는 준비 뒤 전달한다.
  const startupPaths = pathsFromArgv(process.argv);
  createMainWindow(info.appUrl, startupPaths[0] ?? '');
  if (startupPaths.length > 1) deliverExternalPaths(startupPaths.slice(1));
  if (startupPaths.length) console.log('[open] startup paths:', startupPaths.join(' | '));
  trayController = createTrayController({
    resolveIconPath,
    getMainWindow: () => mainWindow,
    focusMainWindow,
    quitApp: quitFromTray,
  });
  // 트레이 아이콘은 설정 '창을 닫으면 트레이로 보내기'가 켜져 있을 때만 둔다.
  // 꺼져 있으면 닫기(X)가 종료이므로 트레이가 필요 없고, 종료 뒤에도 인쇄 감시자는 따로 살아 있다.
  runtime.syncTray = syncTray;
  syncTray();
  startBackupScheduler();
  // 가상 프린터 + 백그라운드 인쇄 감시. 창이 뜬 뒤에 하므로 시작 속도에 영향이 없다.
  void ensurePrintService().catch((err) => console.warn('[print] ensure failed:', err));

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

/**
 * @param {string} appUrl
 * @param {string} [openPath] 시작할 때 바로 열 파일
 */
function createMainWindow(appUrl, openPath = '') {
  let url = appUrl;
  if (openPath) {
    const parsed = new URL(appUrl);
    parsed.searchParams.set('open', openPath);
    url = parsed.toString();
  }
  mainWindow = createAppWindow(url, { main: true, windowId: 'main' });
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
  // 문서 창도 닫기 전에 저장 여부를 묻는다 (메인 창과 같은 계약).
  win.on('close', (event) => {
    if (main) {
      if (!mainCloseApproved) {
        event.preventDefault();
        // 설정 > 종료: 켜져 있으면 트레이로 숨기고, 꺼져 있으면 트레이 Exit 와 같은 종료 흐름을 탄다.
        requestMainClose(closeToTrayEnabled() ? 'hide' : 'quit');
      }
      return;
    }
    if (quitDocumentsConfirmed || closeApprovedDocWindows.delete(win)) return;
    event.preventDefault();
    void confirmDocumentWindowClose(win);
  });

  const webContentsId = win.webContents.id;
  if (!main) documentWindows.add(win);

  // 렌더러가 새로 로드되면(새로고침·크래시 복구) 열려 있던 저장 확인창과 응답 경로가 사라진다.
  // 진행 중이던 닫기 요청을 취소해 두지 않으면 이후 닫기 클릭이 영원히 무시된다.
  win.webContents.on('did-start-loading', () => {
    if (main) {
      if (closeReason) console.log('[close-debug] renderer reloaded, drop pending close =', closeReason);
      closeReason = null;
      // 새로 로드되는 렌더러는 다시 준비 신호를 보낼 때까지 경로를 받을 수 없다.
      rendererOpenReady = false;
      return;
    }
    const waiter = pendingDocCloseWaiters.get(webContentsId);
    if (waiter) {
      pendingDocCloseWaiters.delete(webContentsId);
      waiter(false);
    }
  });

  win.on('closed', () => {
    if (main) {
      mainWindow = null;
    } else {
      documentWindows.delete(win);
      pendingDocCloseWaiters.delete(webContentsId);
      disposeEngineSession(windowId);
    }
  });

  void win.loadURL(appUrl);
  return win;
}

/** 설정에 맞게 트레이 아이콘을 만들거나 없앤다. */
function syncTray() {
  if (!trayController) return;
  if (closeToTrayEnabled()) trayController.create();
  else trayController.destroy();
}

/** 설정 '창을 닫으면 트레이로 보내기'. 읽지 못하면 기존 동작(트레이)을 유지한다. */
function closeToTrayEnabled() {
  try {
    return getSettings().closeToTray !== false;
  } catch {
    return true;
  }
}

/**
 * 메인 창을 숨기거나 종료하기 전에 렌더러가 저장 여부를 묻도록 요청한다.
 * 응답은 frame:closeResponse 로 온다. 취소하면 아무 일도 일어나지 않는다.
 * @param {'hide' | 'quit'} reason
 */
function requestMainClose(reason) {
  console.log('[close-debug] requestMainClose', reason, 'pending =', closeReason);
  if (!mainWindow || mainWindow.isDestroyed() || closeReason) return;
  closeReason = reason;
  mainWindow.show();
  mainWindow.focus();
  if (mainWindow.webContents.isCrashed()) {
    applyCloseDecision(true);
    return;
  }
  mainWindow.webContents.send('frame:closeRequest');
}

/** @param {boolean} proceed */
function applyCloseDecision(proceed) {
  console.log('[close-debug] main decision proceed =', proceed, 'reason =', closeReason);
  const reason = closeReason;
  closeReason = null;
  if (!reason || !proceed || !mainWindow || mainWindow.isDestroyed()) return;
  // 숨겨 둘 트레이가 없으면(설정이 막 꺼진 경우 등) 창을 되살릴 길이 없으므로 숨기지 않고 종료한다.
  if (reason === 'quit' || !trayController?.isActive()) {
    mainCloseApproved = true;
    app.quit();
  } else {
    mainWindow.hide();
  }
}

function quitFromTray() {
  // 실제 종료는 before-quit 에서 저장 여부를 확인한 뒤 진행한다.
  app.quit();
}

/**
 * 문서 창에 저장 여부 확인을 요청하고, 닫아도 되는지(true) 기다린다.
 * 응답은 frame:closeResponse 로 온다.
 * @param {BrowserWindow} win
 * @returns {Promise<boolean>}
 */
function askDocumentWindowClose(win) {
  return new Promise((resolve) => {
    if (win.isDestroyed()) return resolve(true);
    if (win.webContents.isCrashed()) return resolve(true);
    const id = win.webContents.id;
    if (pendingDocCloseWaiters.has(id)) return resolve(false);
    pendingDocCloseWaiters.set(id, resolve);
    win.show();
    win.focus();
    win.webContents.send('frame:closeRequest');
  });
}

/** X 로 닫는 문서 창: 저장 여부를 묻고, 확인이 끝나면 실제로 닫는다. */
async function confirmDocumentWindowClose(win) {
  console.log('[close-debug] document window close requested');
  const proceed = await askDocumentWindowClose(win);
  console.log('[close-debug] document window decision proceed =', proceed);
  if (proceed && !win.isDestroyed()) {
    closeApprovedDocWindows.add(win);
    win.close();
  }
}

/**
 * 종료할 때 열린 문서 창마다 저장 여부를 묻는다. 하나라도 취소하면 종료를 멈춘다.
 * 메인 창 확인이 끝난 뒤(before-quit)에 호출된다.
 */
async function confirmDocumentWindowsForQuit() {
  if (quitDocumentsConfirming) return;
  quitDocumentsConfirming = true;
  try {
    for (const win of [...documentWindows]) {
      if (win.isDestroyed()) continue;
      const proceed = await askDocumentWindowClose(win);
      if (!proceed) {
        // 종료 취소: 메인 창 승인도 되돌려 다음 X 클릭이 숨김으로 동작하게 한다.
        mainCloseApproved = false;
        return;
      }
    }
    quitDocumentsConfirmed = true;
    app.quit();
  } finally {
    quitDocumentsConfirming = false;
  }
}

function hasOpenDocumentWindows() {
  for (const win of documentWindows) {
    if (!win.isDestroyed()) return true;
  }
  return false;
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

  /** 렌더러가 저장 여부 확인을 끝냈다. proceed 가 true 면 숨기거나 종료한다. */
  ipcMain.on('frame:closeResponse', (event, proceed) => {
    // 문서 창이 저장 여부 확인을 끝낸 응답이면 그 창의 대기자에게 넘긴다.
    const waiter = pendingDocCloseWaiters.get(event.sender.id);
    if (waiter) {
      pendingDocCloseWaiters.delete(event.sender.id);
      waiter(proceed === true);
      return;
    }
    if (!mainWindow || BrowserWindow.fromWebContents(event.sender) !== mainWindow) return;
    applyCloseDecision(proceed === true);
  });

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

  /** 상단 오른쪽 ? 단추: 스플래시 형태의 정보 창을 토글한다. */
  ipcMain.handle('frame:showAboutSplash', () => toggleAboutSplash({ iconPath: resolveIconPath() }));
  registerSplashIpc();

  /** 메인 창 렌더러가 frame:openPaths 를 받을 준비를 마쳤다. 쌓아 둔 경로를 보낸다. */
  ipcMain.on('frame:openPathsReady', (event) => {
    if (!mainWindow || mainWindow.isDestroyed() || event.sender !== mainWindow.webContents) return;
    rendererOpenReady = true;
    flushOpenPaths();
  });

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
  if (!mainCloseApproved && mainWindow && !mainWindow.isDestroyed()) {
    // 저장 여부 확인이 끝나야 실제로 종료한다. 취소하면 종료하지 않는다.
    event.preventDefault();
    requestMainClose('quit');
    return;
  }
  if (!quitDocumentsConfirmed && hasOpenDocumentWindows()) {
    // 메인 창 확인 뒤, 열린 문서 창의 저장 여부도 묻고 나서 종료한다.
    event.preventDefault();
    void confirmDocumentWindowsForQuit();
    return;
  }
  isQuitting = true;
  if (quitCleanupStarted) return;
  quitCleanupStarted = true;

  stopBackupScheduler();
  trayController?.destroy();
  trayController = null;
  // 앱을 끈 직후에도 인쇄 PDF 가 열리도록 백그라운드 감시자가 살아 있게 한다.
  keepWatchAfterQuit();
  if (!serverManager) return;

  // Release the port before the process exits.
  event.preventDefault();
  void serverManager
    .stop()
    .catch((err) => console.warn('[server] stop failed:', err))
    .finally(() => app.exit(0));
});
