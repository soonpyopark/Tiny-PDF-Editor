/**
 * 스플래시 화면 (원본 Tiny PDF Editor 의 splash_screen.py 를 옮김).
 * 짙은 남색 배경에 앱 아이콘, 앱 이름·버전, 제작자 링크, 빌드 정보를 가운데 정렬로 보여준다.
 *
 * - 시작 스플래시: 메인 창이 준비되면 최소 표시 시간(700ms)을 채운 뒤 닫는다.
 * - 정보 스플래시(상단 오른쪽 ? 단추): 바깥을 클릭하거나 Esc 를 누르면 닫히고,
 *   같은 메뉴를 다시 누르면 토글된다. 링크 클릭은 닫지 않는다.
 */
import { BrowserWindow, ipcMain, nativeImage, shell } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  APP_BUILD_STAMP,
  APP_NAME,
  APP_VERSION,
  formatAppBuildStamp,
} from '../shared/constants.js';

/** 원본 SPLASH_MIN_MS */
const SPLASH_MIN_MS = 700;
/** 원본 version.py 의 제작자 링크 */
const AUTHOR_URL =
  'https://note4all.tistory.com/category/' +
  '%EC%86%8C%ED%94%84%ED%8A%B8%EC%9B%A8%EC%96%B4%20%EC%97%B0%EA%B5%AC%EC%86%8C/' +
  'TIny%20PDF%20Editor';
const AUTHOR_LINK_TEXT = 'https://note4all.tistory.com';
const SPLASH_BG = '#0a1a33';
const ICON_SIZE = 72;
const WIDTH = 540;
// 가로를 460 → 540 으로 80 늘렸으므로 세로도 150 → 230 으로 80 늘린다 (위·아래 여백이 각각 40 씩 늘어난다).
const HEIGHT = 230;

const PRELOAD_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), 'splashPreload.cjs');

/** 현재 열려 있는 정보 스플래시 (하나만 유지) */
/** @type {BrowserWindow | null} */
let aboutWin = null;

/** @param {string} value */
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * 아이콘을 data URL 로 넣어 두면 file:// 경로 차단 문제를 피할 수 있다.
 * @param {string | undefined} iconPath
 * @returns {string}
 */
function iconDataUrl(iconPath) {
  if (!iconPath || !fs.existsSync(iconPath)) return '';
  const image = nativeImage.createFromPath(iconPath);
  if (image.isEmpty()) return '';
  return image.resize({ width: ICON_SIZE, height: ICON_SIZE, quality: 'best' }).toDataURL();
}

/** @param {string | undefined} iconPath */
function buildHtml(iconPath) {
  const src = iconDataUrl(iconPath);
  const img = src ? `<img src="${src}" alt="" />` : '';
  const build = APP_BUILD_STAMP ? `<div class="build">${escapeHtml(formatAppBuildStamp(APP_BUILD_STAMP))}</div>` : '';
  return `<!doctype html>
<html lang="ko"><head><meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'" />
<style>
  html, body { margin: 0; height: 100%; overflow: hidden; background: ${SPLASH_BG};
    font-family: "Segoe UI", "Malgun Gothic", sans-serif; user-select: none; }
  .row { height: 100%; box-sizing: border-box; padding: 0 56px 0 36px;
    display: flex; align-items: center; justify-content: center; gap: 16px; }
  img { width: ${ICON_SIZE}px; height: ${ICON_SIZE}px; flex: none; }
  .title { color: #ffffff; font-size: 22px; font-weight: 700; white-space: nowrap; }
  .meta { display: flex; flex-direction: column; gap: 3px; margin-top: 8px; }
  .link { color: #9aa8b8; font-size: 11px; text-decoration: none; cursor: pointer; }
  .build { color: #6e7b8c; font-size: 11px; }
</style></head>
<body><div class="row">${img}
  <div>
    <div class="title">${escapeHtml(APP_NAME)} v${escapeHtml(APP_VERSION)}</div>
    <div class="meta">
      <a class="link" href="${escapeHtml(AUTHOR_URL)}">${escapeHtml(AUTHOR_LINK_TEXT)}</a>
      ${build}
    </div>
  </div>
</div></body></html>`;
}

/**
 * @param {{ iconPath?: string, about?: boolean }} options
 * @returns {BrowserWindow}
 */
function buildWindow({ iconPath, about }) {
  const win = new BrowserWindow({
    width: WIDTH,
    height: HEIGHT,
    frame: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    closable: !about,
    skipTaskbar: true,
    alwaysOnTop: true,
    center: true,
    show: false,
    backgroundColor: SPLASH_BG,
    autoHideMenuBar: true,
    webPreferences: {
      preload: PRELOAD_PATH,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // 링크는 스플래시 안에서 열지 않고 기본 브라우저로 보낸다.
  win.webContents.on('will-navigate', (event, url) => {
    event.preventDefault();
    if (/^https?:/i.test(url)) void shell.openExternal(url);
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });

  void win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(buildHtml(iconPath))}`);
  win.once('ready-to-show', () => {
    if (win.isDestroyed()) return;
    win.show();
    if (about) win.focus();
  });
  return win;
}

/**
 * 시작 스플래시를 만든다.
 * @param {{ iconPath?: string }} options
 * @returns {{ closeWhenReady: () => void, close: () => void }}
 */
export function createSplashWindow({ iconPath } = {}) {
  const startedAt = Date.now();
  const win = buildWindow({ iconPath, about: false });

  let timer = null;
  const close = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    if (!win.isDestroyed()) win.destroy();
  };

  return {
    /** 메인 창이 준비되면 호출: 최소 표시 시간이 지난 뒤 닫는다. */
    closeWhenReady() {
      if (timer || win.isDestroyed()) return;
      const wait = Math.max(0, SPLASH_MIN_MS - (Date.now() - startedAt));
      timer = setTimeout(close, wait);
    },
    /** 오류 등으로 즉시 닫을 때 */
    close,
  };
}

/** 정보 스플래시를 닫는다. */
function closeAbout() {
  const win = aboutWin;
  aboutWin = null;
  if (win && !win.isDestroyed()) win.destroy();
}

/**
 * 상단 오른쪽 ? 단추: 열려 있으면 닫고, 아니면 연다 (원본 toggle_about_splash).
 * @param {{ iconPath?: string }} options
 * @returns {boolean} 열렸으면 true, 닫았으면 false
 */
export function toggleAboutSplash({ iconPath } = {}) {
  if (aboutWin && !aboutWin.isDestroyed()) {
    closeAbout();
    return false;
  }
  const win = buildWindow({ iconPath, about: true });
  aboutWin = win;
  // 바깥을 클릭해 포커스를 잃으면 닫는다 (원본 _AboutDismissFilter 와 같은 동작).
  win.on('blur', () => {
    if (aboutWin === win) closeAbout();
  });
  win.on('closed', () => {
    if (aboutWin === win) aboutWin = null;
  });
  return true;
}

/** 스플래시 창의 클릭·Esc 입력을 받아 정보 스플래시를 닫는다 (렌더러 → 메인). */
export function registerSplashIpc() {
  ipcMain.on('splash:dismiss', (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win && win === aboutWin) closeAbout();
  });
}
