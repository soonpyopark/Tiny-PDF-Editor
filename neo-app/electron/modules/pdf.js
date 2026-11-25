/**
 * Local bridge to Tiny PDF Editor's Python engine (pdf_editor.engine).
 * The engine is a child process on this PC. It is not exposed as its own port.
 */
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { app, BrowserWindow, clipboard, dialog, shell } from 'electron';
import { ApiError, currentWindowId, defineApi } from '../api/registry.js';
import {
  buildPrintHtml,
  dpiForSheets,
  layoutSheets,
  normalizePrintOptions,
  renderZoomFor,
} from '../../shared/printLayout.js';
import {
  disablePrinter,
  enablePrinter,
  launcherCommand,
  launcher as appLauncher,
  printerInstalled,
  printerSupported,
} from '../printService.js';
import {
  convertTextFileToPdf,
  isHtmlPath,
  isTextPath,
} from '../textPdfExport.mjs';

// neo-app/electron/modules/ 기준 두 단계 위가 Tiny PDF Editor - neo 루트(pdf_editor 패키지가 있는 곳).
const engineRoot =
  process.env.TINY_PDF_ROOT ||
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

const OPEN_FILTERS = [
  { name: 'PDF', extensions: ['pdf'] },
  { name: '이미지', extensions: ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'tif', 'tiff', 'webp'] },
  { name: '한글', extensions: ['hwp', 'hwpx'] },
  { name: '텍스트·HTML', extensions: ['txt', 'md', 'markdown', 'json', 'html', 'htm'] },
];

/** 파일 열기: 전체(*.*)를 기본 필터로 두고 종류별 필터를 뒤에 붙인다. */
const OPEN_FILTERS_WITH_ALL = [{ name: '전체', extensions: ['*'] }, ...OPEN_FILTERS];

const RECENT_LIMIT = 12;
const recentPath = path.join(os.homedir(), '.tiny-pdf-editor-neo', 'recent.json');

/**
 * 엔진을 띄우는 방법.
 *   - 패키지 앱: resources/engine/tiny-pdf-engine(.exe) (PyInstaller 로 동결, Python 설치 불필요)
 *   - 개발 실행: 시스템 Python 의 `python -m pdf_editor.engine`
 * @type {{ cmd: string, prefix: string[], cwd: string, frozen: boolean } | null}
 */
let engineCommand = null;
/**
 * 창(windowId)마다 엔진 자식 프로세스 하나와 요청 큐를 가진다.
 * 한 창의 문서가 다른 창의 문서와 섞이지 않도록 나눈다.
 * @type {Map<string, { windowId: string, child: import('node:child_process').ChildProcess | null, pending: Map<number, { resolve: (msg: any) => void, reject: (err: Error) => void }>, chain: Promise<unknown>, seq: number, stderrTail: string }>}
 */
const sessions = new Map();
/** @type {{ pdf: string, count: number } | null} */
let pageClipboard = null;

const SLOW_OPS = new Set([
  'insert',
  'ocr',
  'reduceSize',
  'hwpConvert',
  'piiScan',
  'piiRedact',
  'exportImages',
  'exportPagesImages',
  'exportPagesPdf',
  'merge',
  'mergeFiles',
  'movePages',
]);

function ownerWindow() {
  return BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
}

function readRecent() {
  try {
    const raw = fs.readFileSync(recentPath, 'utf8');
    const list = JSON.parse(raw);
    return Array.isArray(list) ? list.filter((item) => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function writeRecent(list) {
  fs.mkdirSync(path.dirname(recentPath), { recursive: true });
  fs.writeFileSync(recentPath, JSON.stringify(list.slice(0, RECENT_LIMIT), null, 2), 'utf8');
}

function rememberRecent(filePath) {
  if (!filePath) return;
  const next = [filePath, ...readRecent().filter((item) => item !== filePath)];
  writeRecent(next);
}

/* ---- PDF 병합 (Tiny merge_pdf_dialog.py 와 같은 규칙) ---- */

const mergePrefsPath = path.join(os.homedir(), '.tiny-pdf-editor-neo', 'merge.json');
// 보기 > 새 창으로 열기 / 새 탭으로 열기 설정 (원본 app_settings.open_in_new_window, 기본값 새 창).
const viewPrefsPath = path.join(os.homedir(), '.tiny-pdf-editor-neo', 'view.json');

function readOpenInNewWindow() {
  try {
    const raw = JSON.parse(fs.readFileSync(viewPrefsPath, 'utf8'));
    return typeof raw?.openInNewWindow === 'boolean' ? raw.openInNewWindow : true;
  } catch {
    return true;
  }
}

function writeOpenInNewWindow(enabled) {
  fs.mkdirSync(path.dirname(viewPrefsPath), { recursive: true });
  fs.writeFileSync(viewPrefsPath, JSON.stringify({ openInNewWindow: Boolean(enabled) }, null, 2), 'utf8');
}
const MERGE_SUPPORTED_EXT = new Set([
  '.pdf',
  '.png',
  '.jpg',
  '.jpeg',
  '.bmp',
  '.gif',
  '.tif',
  '.tiff',
  '.webp',
  '.hwp',
  '.hwpx',
  '.txt',
  '.md',
  '.markdown',
  '.json',
  '.html',
  '.htm',
]);

function isDirectory(target) {
  try {
    return fs.statSync(target).isDirectory();
  } catch {
    return false;
  }
}

function defaultMergeFolder() {
  const downloads = path.join(os.homedir(), 'Downloads');
  return isDirectory(downloads) ? downloads : os.homedir();
}

function readMergeSaveFolder() {
  try {
    const raw = JSON.parse(fs.readFileSync(mergePrefsPath, 'utf8'));
    const folder = String(raw?.saveFolder || '');
    if (folder && isDirectory(folder)) return folder;
  } catch {
    /* fall through to default */
  }
  return defaultMergeFolder();
}

function writeMergeSaveFolder(folder) {
  fs.mkdirSync(path.dirname(mergePrefsPath), { recursive: true });
  fs.writeFileSync(mergePrefsPath, JSON.stringify({ saveFolder: folder }, null, 2), 'utf8');
}

/* ---- 한글 → PDF 설정 (원본 app_settings.hwp_save_*) ---- */

const hwpPrefsPath = path.join(os.homedir(), '.tiny-pdf-editor-neo', 'hwp.json');

function isHwpPath(filePath) {
  return /\.(hwp|hwpx)$/i.test(String(filePath || ''));
}

function readHwpPrefs() {
  const fallback = { besideSource: true, saveFolder: defaultMergeFolder() };
  try {
    const raw = JSON.parse(fs.readFileSync(hwpPrefsPath, 'utf8'));
    const folder = String(raw?.saveFolder || '');
    return {
      besideSource: typeof raw?.besideSource === 'boolean' ? raw.besideSource : fallback.besideSource,
      saveFolder: folder && isDirectory(folder) ? folder : fallback.saveFolder,
    };
  } catch {
    return fallback;
  }
}

function writeHwpPrefs(prefs) {
  fs.mkdirSync(path.dirname(hwpPrefsPath), { recursive: true });
  fs.writeFileSync(hwpPrefsPath, JSON.stringify(prefs, null, 2), 'utf8');
}

/** 같은 이름이 있으면 "이름 (2).pdf", "이름 (3).pdf"... 를 찾는다. */
function uniquePdfPath(folder, stemName) {
  let candidate = path.join(folder, `${stemName}.pdf`);
  if (!fs.existsSync(candidate)) return candidate;
  for (let index = 2; ; index += 1) {
    candidate = path.join(folder, `${stemName} (${index}).pdf`);
    if (!fs.existsSync(candidate)) return candidate;
  }
}

/**
 * TXT/MD/HTML → Chromium printToPDF.
 * TXT·MD 실패 시에만 엔진 MuPDF 조판으로 폴백 (HTML 은 Chromium 전용).
 * @param {string} source
 * @param {string} target
 */
async function textFileToPdfPath(source, target) {
  try {
    return await convertTextFileToPdf(source, target);
  } catch (error) {
    if (isHtmlPath(source)) throw error;
    const message = error instanceof Error ? error.message : String(error || '');
    console.warn('[textPdfExport] Chromium convert failed, falling back to engine:', message);
    const result = await engineOp({ op: 'textConvert', path: source, output: target });
    return String(result.path || target);
  }
}

/** @param {string} source */
async function textConvertToTempPdf(source) {
  const stemName = path.basename(source, path.extname(source)) || 'document';
  const target = uniquePdfPath(os.tmpdir(), `tiny-neo-text-${stemName}`);
  return textFileToPdfPath(source, target);
}

/**
 * 열기·삽입·병합 전에 텍스트 경로를 임시 PDF 로 바꾼다.
 * @param {string[]} paths
 * @returns {Promise<{ paths: string[], temps: string[] }>}
 */
async function materializeTextPaths(paths) {
  const out = [];
  const temps = [];
  for (const raw of paths) {
    const filePath = String(raw || '');
    if (isTextPath(filePath) && fs.existsSync(filePath)) {
      const converted = await textConvertToTempPdf(filePath);
      out.push(converted);
      temps.push(converted);
    } else {
      out.push(filePath);
    }
  }
  return { paths: out, temps };
}

/** Same rules as merge_pdf_dialog._sanitize_filename. */
function sanitizeMergeName(name) {
  let base = String(name ?? '').trim() || '병합';
  if (base.toLowerCase().endsWith('.pdf')) base = base.slice(0, -4);
  const cleaned = base.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/[ .]+$/, '');
  return cleaned || '병합';
}

function passwordMap(raw) {
  if (!raw || typeof raw !== 'object') return {};
  return Object.fromEntries(
    Object.entries(raw)
      .map(([key, value]) => [String(key), String(value ?? '')])
      .filter(([, value]) => value),
  );
}

function frozenEngineExe() {
  const explicit = String(process.env.TINY_PDF_ENGINE ?? '').trim();
  if (explicit) return explicit;
  if (!app.isPackaged) return '';
  const name = process.platform === 'win32' ? 'tiny-pdf-engine.exe' : 'tiny-pdf-engine';
  return path.join(process.resourcesPath, 'engine', name);
}

function resolveEngine() {
  if (engineCommand) return engineCommand;
  const frozen = frozenEngineExe();
  if (frozen) {
    if (!fs.existsSync(frozen)) {
      throw new ApiError(`PDF 엔진 파일을 찾지 못했습니다: ${frozen}`);
    }
    engineCommand = { cmd: frozen, prefix: [], cwd: path.dirname(frozen), frozen: true };
    return engineCommand;
  }
  const python = resolvePython();
  engineCommand = { cmd: python.cmd, prefix: python.prefix, cwd: engineRoot, frozen: false };
  return engineCommand;
}

/** @type {{ cmd: string, prefix: string[] } | null} */
let pythonCommand = null;

function resolvePython() {
  if (pythonCommand) return pythonCommand;
  /** @type {{ cmd: string, prefix: string[], probe: string[] }[]} */
  const candidates = [];
  if (process.env.TINY_PDF_PYTHON) {
    candidates.push({ cmd: process.env.TINY_PDF_PYTHON, prefix: [], probe: ['-c', 'import pymupdf'] });
  }
  const listed = spawnSync('py', ['-0p'], { windowsHide: true, encoding: 'utf8' });
  if (listed.status === 0) {
    for (const line of listed.stdout.split(/\r?\n/)) {
      const match = /-V:(\d+\.\d+(?:-\d+)?)/.exec(line);
      if (!match || match[1].includes('-32')) continue;
      candidates.push({
        cmd: 'py',
        prefix: [`-${match[1]}`],
        probe: [`-${match[1]}`, '-c', 'import pymupdf'],
      });
    }
  }
  candidates.push({ cmd: 'python', prefix: [], probe: ['-c', 'import pymupdf'] });
  for (const candidate of candidates) {
    const probe = spawnSync(candidate.cmd, candidate.probe, { windowsHide: true, encoding: 'utf8' });
    if (probe.status === 0) {
      pythonCommand = { cmd: candidate.cmd, prefix: candidate.prefix };
      return pythonCommand;
    }
  }
  throw new ApiError(
    'PyMuPDF가 설치된 64비트 Python을 찾지 못했습니다. TINY_PDF_PYTHON 으로 지정할 수 있습니다.',
  );
}

function failPending(session, error) {
  for (const item of session.pending.values()) item.reject(error);
  session.pending.clear();
}

function sessionFor(windowId) {
  let session = sessions.get(windowId);
  if (!session) {
    session = { windowId, child: null, pending: new Map(), chain: Promise.resolve(), seq: 0, stderrTail: '' };
    sessions.set(windowId, session);
  }
  return session;
}

function ensureEngine(session) {
  if (session.child && !session.child.killed && session.child.exitCode == null) return;
  const engine = resolveEngine();
  session.stderrTail = '';
  const engineArgs = engine.frozen ? [] : [...engine.prefix, '-u', '-m', 'pdf_editor.engine'];
  const child = spawn(engine.cmd, engineArgs, {
    cwd: engine.cwd,
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  session.child = child;
  child.stderr?.on('data', (chunk) => {
    session.stderrTail = (session.stderrTail + String(chunk)).slice(-4000);
  });
  const lines = readline.createInterface({ input: child.stdout });
  lines.on('line', (line) => {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    if (message?.type === 'progress') {
      // 파일·쪽 단위 진행. 요청을 끝내지 않고 이 세션(창)의 화면으로만 보낸다.
      for (const win of BrowserWindow.getAllWindows()) {
        if (!win.isDestroyed()) {
          win.webContents.send('pdf:log', {
            windowId: session.windowId,
            id: message.id,
            progress: {
              op: String(message.op ?? ''),
              current: Number(message.current) || 0,
              total: Number(message.total) || 0,
              label: String(message.label ?? ''),
            },
          });
        }
      }
      return;
    }
    if (message?.type === 'log') {
      // 진행 로그는 요청을 끝내지 않는다. 열린 창의 터미널로만 보낸다.
      // 로그는 이 세션(창)의 엔진에서 온 것만 그 창으로 보낸다. 렌더러가 windowId 로 거른다.
      for (const win of BrowserWindow.getAllWindows()) {
        if (!win.isDestroyed()) {
          win.webContents.send('pdf:log', {
            windowId: session.windowId,
            id: message.id,
            message: String(message.message ?? ''),
          });
        }
      }
      return;
    }
    const item = session.pending.get(message.id);
    if (!item) return;
    session.pending.delete(message.id);
    item.resolve(message);
  });
  child.on('exit', (code) => {
    if (session.child === child) session.child = null;
    const detail = session.stderrTail.trim();
    failPending(
      session,
      new ApiError(`PDF 엔진이 종료되었습니다. (${code ?? '?'})${detail ? `\n${detail}` : ''}`),
    );
  });
}

/**
 * @param {Record<string, unknown>} payload
 */
function callEngine(payload) {
  const session = sessionFor(currentWindowId());
  const run = session.chain.then(
    () =>
      new Promise((resolve, reject) => {
        try {
          ensureEngine(session);
        } catch (error) {
          reject(error);
          return;
        }
        const id = ++session.seq;
        const timeoutMs = SLOW_OPS.has(String(payload.op)) ? 300_000 : payload.op === 'render' ? 120_000 : 60_000;
        const timeout = setTimeout(() => {
          session.pending.delete(id);
          reject(new ApiError('PDF 엔진 응답이 없습니다.'));
        }, timeoutMs);
        session.pending.set(id, {
          resolve: (message) => {
            clearTimeout(timeout);
            resolve(message);
          },
          reject: (error) => {
            clearTimeout(timeout);
            reject(error);
          },
        });
        session.child.stdin.write(`${JSON.stringify({ id, ...payload })}\n`);
      }),
  );
  session.chain = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

/**
 * 문서 창이 닫히면 그 창의 엔진 프로세스를 끈다. 대기 중인 요청은 실패로 끝난다.
 * @param {string} windowId
 */
export function disposeEngineSession(windowId) {
  disposeSessionsWhere(
    (key) => key === windowId || key.startsWith(`${windowId}__`),
    '창이 닫혀 PDF 엔진을 종료했습니다.',
  );
}

/**
 * 조건에 맞는 엔진 세션을 모두 끈다. 대기 중인 요청은 실패로 끝난다.
 * @param {(key: string) => boolean} match
 * @param {string} reason
 */
function disposeSessionsWhere(match, reason) {
  for (const key of [...sessions.keys()]) {
    if (!match(key)) continue;
    const session = sessions.get(key);
    sessions.delete(key);
    if (!session) continue;
    failPending(session, new ApiError(reason));
    if (session.child && session.child.exitCode == null) session.child.kill();
    session.child = null;
  }
}

async function engineOp(payload) {
  const message = await callEngine(payload);
  if (message?.ok) return message;
  if (message?.code === 'password' || message?.code === 'password_rejected') {
    return {
      needsPassword: true,
      rejected: message.code === 'password_rejected',
      error: message.error || '비밀번호가 필요합니다.',
    };
  }
  throw new ApiError(message?.error || 'PDF 엔진 오류');
}

async function openPath(filePath, password) {
  let openTarget = filePath;
  let forgetPath = false;
  let tempPdf = null;
  if (isTextPath(filePath) && fs.existsSync(filePath)) {
    tempPdf = await textConvertToTempPdf(filePath);
    openTarget = tempPdf;
    forgetPath = true;
  }
  try {
    const opened = await engineOp({
      op: 'open',
      path: openTarget,
      password: password ? String(password) : null,
      forgetPath,
    });
    if (opened.needsPassword) {
      return {
        needsPassword: true,
        rejected: opened.rejected,
        path: filePath,
        error: opened.error,
      };
    }
    rememberRecent(filePath);
    return { doc: opened.doc, path: filePath };
  } finally {
    if (tempPdf) {
      try {
        fs.unlinkSync(tempPdf);
      } catch {
        /* 임시 PDF 정리는 실패해도 열기 결과에 영향 없음 */
      }
    }
  }
}

export function register() {
  defineApi('pdf.status', 'user', async () => {
    try {
      resolveEngine();
      await engineOp({ op: 'ping' });
      // 시작 시 빈 문서 탭을 만들지 판단하려고 현재 문서 상태를 함께 돌려준다.
      const info = await engineOp({ op: 'info' });
      return { ready: true, root: engineRoot, doc: info.doc ?? null };
    } catch (error) {
      return {
        ready: false,
        root: engineRoot,
        error: error instanceof Error ? error.message : '엔진을 시작하지 못했습니다.',
      };
    }
  });

  defineApi('pdf.recent', 'user', async () => {
    const items = readRecent().filter((filePath) => {
      try {
        return fs.existsSync(filePath);
      } catch {
        return false;
      }
    });
    writeRecent(items);
    return { items };
  });

  /** 원본 최근 파일 우클릭 > 목록에서 제거: 그 항목만 지우고 남은 목록을 돌려준다. */
  defineApi('pdf.recentRemove', 'user', async (body) => {
    const target = String(body?.path || '');
    const items = readRecent().filter((filePath) => filePath !== target);
    writeRecent(items);
    return { items };
  });

  /** 원본 최근 파일 우클릭 > 파일 위치 열기: 탐색기에서 해당 파일을 선택한 상태로 연다. */
  defineApi('pdf.recentReveal', 'user', async (body) => {
    const target = String(body?.path || '');
    if (!target || !fs.existsSync(target)) {
      throw new Error('파일을 찾을 수 없습니다.');
    }
    shell.showItemInFolder(target);
    return { ok: true };
  });

  /** 원본 최근 파일 > 모두 지우기 */
  defineApi('pdf.recentClear', 'user', async () => {
    writeRecent([]);
    return { items: [] };
  });

  defineApi('pdf.pickOpen', 'user', async () => {
    const win = ownerWindow();
    const options = {
      title: 'PDF 열기',
      filters: OPEN_FILTERS_WITH_ALL,
      properties: ['openFile'],
    };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths[0]) return { canceled: true };
    const opened = await openPath(picked.filePaths[0]);
    if (opened.needsPassword) {
      return {
        canceled: false,
        needsPassword: true,
        rejected: opened.rejected,
        path: opened.path,
        error: opened.error,
      };
    }
    return { canceled: false, doc: opened.doc };
  });

  defineApi('pdf.open', 'user', async (body) => {
    const filePath = String(body?.path || '').trim();
    if (!filePath) throw new ApiError('파일 경로가 없습니다.');
    return openPath(filePath, body?.password);
  });

  /** 파일만 고른다 (열지는 않음). 새 창으로 열지 같은 창으로 열지는 렌더러가 정한다. */
  defineApi('pdf.pickPath', 'user', async () => {
    const win = ownerWindow();
    const options = {
      title: 'PDF 열기',
      filters: OPEN_FILTERS_WITH_ALL,
      properties: ['openFile'],
    };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths[0]) return { canceled: true };
    return { canceled: false, path: picked.filePaths[0] };
  });

  defineApi('pdf.openTargetGet', 'user', async () => ({ openInNewWindow: readOpenInNewWindow() }));

  defineApi('pdf.openTargetSet', 'user', async (body) => {
    const enabled = Boolean(body?.openInNewWindow);
    writeOpenInNewWindow(enabled);
    return { openInNewWindow: enabled };
  });

  defineApi('pdf.new', 'user', async () => {
    const created = await engineOp({ op: 'new' });
    return { doc: created.doc };
  });

  // 탭 하나를 닫을 때 그 탭의 엔진 프로세스만 끈다. 요청 헤더의 세션 키(창 또는 창__탭)와 정확히 일치하는 것만 끈다.
  defineApi('pdf.closeTab', 'user', async (_body, ctx) => {
    const key = String(ctx?.windowId || '');
    if (!key) return { closed: false };
    disposeSessionsWhere((item) => item === key, '탭이 닫혀 PDF 엔진을 종료했습니다.');
    return { closed: true };
  });

  defineApi('pdf.render', 'user', async (body) => {
    const index = Number(body?.index);
    if (!Number.isInteger(index) || index < 0) throw new ApiError('페이지 번호가 올바르지 않습니다.');
    const rendered = await engineOp({
      op: 'render',
      index,
      zoom: Number(body?.zoom) || 1,
      thumb: Boolean(body?.thumb),
    });
    return { png: rendered.png, width: rendered.width, height: rendered.height };
  });

  defineApi('pdf.pickSave', 'user', async () => {
    const win = ownerWindow();
    const options = {
      title: 'PDF 저장',
      filters: [{ name: 'PDF', extensions: ['pdf'] }],
    };
    const picked = win ? await dialog.showSaveDialog(win, options) : await dialog.showSaveDialog(options);
    if (picked.canceled || !picked.filePath) return { canceled: true };
    const saved = await engineOp({ op: 'save', path: picked.filePath });
    rememberRecent(saved.path || picked.filePath);
    return { canceled: false, doc: saved.doc, path: saved.path };
  });

  defineApi('pdf.save', 'user', async (body) => {
    const saved = await engineOp({
      op: 'save',
      path: body?.path ? String(body.path) : null,
    });
    if (saved.path) rememberRecent(saved.path);
    return { doc: saved.doc, path: saved.path };
  });

  defineApi('pdf.markups', 'user', async () => {
    const listed = await engineOp({ op: 'markups' });
    return { entries: listed.entries ?? [] };
  });

  // 연속 스크롤용: 모든 쪽의 크기(pt)를 한 번에 받는다.
  defineApi('pdf.pageSizes', 'user', async () => {
    const listed = await engineOp({ op: 'pageSizes' });
    return { sizes: listed.sizes ?? [] };
  });

  // 본문 드래그 선택. anchor/cursor 는 쪽 이미지 안의 0..1 비율 좌표. 결과 사각형도 같은 비율.
  defineApi('pdf.textSelect', 'user', async (body) => {
    const result = await engineOp({
      op: 'textSelect',
      index: Number(body?.index) || 0,
      anchor: body?.anchor,
      cursor: body?.cursor,
    });
    return { text: result.text ?? '', rects: result.rects ?? [] };
  });

  defineApi('pdf.markupAdd', 'user', async (body) => {
    const result = await engineOp({
      op: 'markupAdd',
      index: Number(body?.index) || 0,
      kind: body?.kind === 'underline' ? 'underline' : 'highlight',
      anchor: body?.anchor,
      cursor: body?.cursor,
      color: body?.color,
    });
    return { doc: result.doc, applied: Boolean(result.applied) };
  });

  defineApi('pdf.markupRemove', 'user', async (body) => {
    const result = await engineOp({
      op: 'markupRemove',
      index: Number(body?.index) || 0,
      point: body?.point,
    });
    return { doc: result.doc, removed: Boolean(result.removed) };
  });

  defineApi('pdf.exportMarkups', 'user', async () => {
    const listed = await engineOp({ op: 'markups' });
    const entries = listed.entries ?? [];
    if (!entries.length) return { empty: true };
    const win = ownerWindow();
    const options = {
      title: '엑셀로 저장',
      filters: [{ name: 'Excel', extensions: ['xlsx'] }],
    };
    const picked = win ? await dialog.showSaveDialog(win, options) : await dialog.showSaveDialog(options);
    if (picked.canceled || !picked.filePath) return { canceled: true };
    const saved = await engineOp({ op: 'exportMarkups', path: picked.filePath });
    return { canceled: false, path: saved.path };
  });

  defineApi('pdf.close', 'user', async () => {
    const closed = await engineOp({ op: 'close' });
    return { doc: closed.doc };
  });

  defineApi('pdf.insert', 'user', async (body) => {
    const win = ownerWindow();
    let paths = Array.isArray(body?.paths) ? body.paths.map(String) : [];
    if (!paths.length) {
      // 기본: 전체 필터, filters 옵션으로 제한 가능
      let filters = [{ name: '전체', extensions: ['*'] }, ...OPEN_FILTERS];
      if (body?.filters === 'restricted') {
        filters = OPEN_FILTERS;
      }
      const options = {
        title: '페이지 추가',
        filters,
        properties: ['openFile', 'multiSelections'],
      };
      const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
      if (picked.canceled || !picked.filePaths.length) return { canceled: true };
      paths = picked.filePaths;
      // 렌더러가 비밀번호를 먼저 모을 수 있게, 고른 경로만 돌려준다.
      if (body?.pickOnly) return { canceled: false, paths };
    }
    const index = Number.isInteger(body?.index) ? Number(body.index) : undefined;
    const materialized = await materializeTextPaths(paths);
    try {
      const result = await engineOp({
        op: 'insert',
        paths: materialized.paths,
        index,
        passwords: passwordMap(body?.passwords),
      });
      if (result.needsPassword) {
        return {
          needsPassword: true,
          path: result.path || null,
          rejected: Boolean(result.rejected),
          doc: result.doc || null,
        };
      }
      let doc = result.doc;
      // 빈 문서에 TXT/MD 하나만 넣으면 엔진이 임시 PDF 경로를 source 로 잡는다 → 떼어 낸다.
      const boundTemp =
        doc?.path &&
        materialized.temps.some((temp) => path.resolve(temp) === path.resolve(String(doc.path)));
      if (boundTemp) {
        const detached = await engineOp({ op: 'detachSource' });
        doc = detached.doc;
      }
      return { canceled: false, doc, added: result.added, stopped: Boolean(result.stopped) };
    } finally {
      for (const temp of materialized.temps) {
        try {
          fs.unlinkSync(temp);
        } catch {
          /* ignore */
        }
      }
    }
  });

  /** 진행 중인 긴 작업(파일 추가·이미지 저장)을 멈추게 한다. 엔진이 다음 파일/쪽 사이에서 알아채고 그때까지 한 것만 남긴다. */
  defineApi('pdf.cancel', 'user', async () => {
    const session = sessionFor(currentWindowId());
    const child = session.child;
    if (child && !child.killed && child.exitCode == null) {
      child.stdin.write(`${JSON.stringify({ op: 'cancel' })}\n`);
    }
    return { ok: true };
  });

  /**
   * "PDF 변환" 대화상자 초기 상태 (병합·개별 변환 공용).
   * 한글 설치 확인은 엔진을 띄워야 하므로 여기서 하지 않는다 → pdf.hwpAvailable (한글 파일이 목록에 들어올 때만).
   */
  defineApi('pdf.convertState', 'user', async () => {
    const prefs = readHwpPrefs();
    return {
      windows: process.platform === 'win32',
      besideSource: prefs.besideSource,
      saveFolder: readMergeSaveFolder(),
    };
  });

  defineApi('pdf.mergePickFiles', 'user', async () => {
    const win = ownerWindow();
    const options = {
      title: 'PDF 병합 - 파일 추가',
      filters: OPEN_FILTERS,
      properties: ['openFile', 'multiSelections'],
    };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths.length) return { canceled: true, paths: [] };
    return { canceled: false, paths: picked.filePaths };
  });

  defineApi('pdf.mergePickFolder', 'user', async () => {
    const win = ownerWindow();
    const options = { title: '파일이 있는 폴더 선택', properties: ['openDirectory'] };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths[0]) return { canceled: true, paths: [] };
    const folder = picked.filePaths[0];
    const paths = fs
      .readdirSync(folder, { withFileTypes: true })
      .filter((entry) => entry.isFile() && MERGE_SUPPORTED_EXT.has(path.extname(entry.name).toLowerCase()))
      .map((entry) => path.join(folder, entry.name))
      .sort();
    return { canceled: false, paths };
  });

  defineApi('pdf.mergePickSaveFolder', 'user', async () => {
    const win = ownerWindow();
    const options = { title: '저장 폴더 선택', properties: ['openDirectory', 'createDirectory'] };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths[0]) return { canceled: true };
    writeMergeSaveFolder(picked.filePaths[0]);
    return { canceled: false, folder: picked.filePaths[0] };
  });

  defineApi('pdf.mergeInspect', 'user', async (body) => {
    const paths = Array.isArray(body?.paths) ? body.paths.map(String).filter(Boolean) : [];
    if (!paths.length) return { items: [] };
    const result = await engineOp({ op: 'mergeInspect', paths, passwords: passwordMap(body?.passwords) });
    return { items: result.items };
  });

  defineApi('pdf.mergePreview', 'user', async (body) => {
    const filePath = String(body?.path || '').trim();
    if (!filePath) throw new ApiError('파일 경로가 없습니다.');
    let previewPath = filePath;
    let tempPdf = null;
    if (isTextPath(filePath) && fs.existsSync(filePath)) {
      tempPdf = await textConvertToTempPdf(filePath);
      previewPath = tempPdf;
    }
    try {
      const result = await engineOp({
        op: 'previewFile',
        path: previewPath,
        password: body?.password ? String(body.password) : null,
      });
      if (result.needsPassword) return { needsPassword: true, rejected: Boolean(result.rejected) };
      if (result.unsupported) return { unsupported: true };
      return { png: result.png, width: result.width, height: result.height, pageCount: result.pageCount };
    } finally {
      if (tempPdf) {
        try {
          fs.unlinkSync(tempPdf);
        } catch {
          /* ignore */
        }
      }
    }
  });

  defineApi('pdf.mergeRun', 'user', async (body) => {
    const paths = Array.isArray(body?.paths) ? body.paths.map(String).filter(Boolean) : [];
    if (!paths.length) throw new ApiError('병합할 파일이 없습니다.');
    const folder = String(body?.folder || '').trim();
    if (!folder || !isDirectory(folder)) throw new ApiError('유효한 저장 폴더를 지정해 주세요.');
    const target = path.join(folder, `${sanitizeMergeName(body?.name)}.pdf`);
    if (fs.existsSync(target) && !body?.overwrite) return { exists: true, target };

    const materialized = await materializeTextPaths(paths);
    try {
      const merged = await engineOp({
        op: 'mergeFiles',
        paths: materialized.paths,
        output: target,
        passwords: passwordMap(body?.passwords),
      });
      if (merged.needsPassword) {
        return { needsPassword: true, path: merged.path, rejected: Boolean(merged.rejected) };
      }
      writeMergeSaveFolder(folder);
      return { canceled: false, path: merged.path, pages: merged.pages, added: merged.added };
    } finally {
      for (const temp of materialized.temps) {
        try {
          fs.unlinkSync(temp);
        } catch {
          /* ignore */
        }
      }
    }
  });

  defineApi('pdf.merge', 'user', async () => {
    const win = ownerWindow();
    const options = {
      title: 'PDF 병합',
      filters: OPEN_FILTERS,
      properties: ['openFile', 'multiSelections'],
    };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || picked.filePaths.length < 1) return { canceled: true };
    const materialized = await materializeTextPaths(picked.filePaths);
    try {
      const merged = await engineOp({ op: 'merge', paths: materialized.paths });
      return { canceled: false, doc: merged.doc, added: merged.added };
    } finally {
      for (const temp of materialized.temps) {
        try {
          fs.unlinkSync(temp);
        } catch {
          /* ignore */
        }
      }
    }
  });

  defineApi('pdf.deletePages', 'user', async (body) => {
    const indices = Array.isArray(body?.indices) ? body.indices.map(Number) : [];
    const result = await engineOp({ op: 'deletePages', indices });
    return { doc: result.doc };
  });

  defineApi('pdf.movePages', 'user', async (body) => {
    const indices = Array.isArray(body?.indices) ? body.indices.map(Number) : [];
    const targetIndex = Number.isInteger(body?.targetIndex) ? Number(body.targetIndex) : 0;
    const result = await engineOp({ op: 'movePages', indices, targetIndex });
    return { doc: result.doc, insertAt: result.insertAt, count: result.count };
  });

  defineApi('pdf.insertBlank', 'user', async (body) => {
    const index = Number.isInteger(body?.index) ? Number(body.index) : undefined;
    const result = await engineOp({ op: 'insertBlank', index });
    return { doc: result.doc, index: result.index };
  });

  defineApi('pdf.rotatePages', 'user', async (body) => {
    const indices = Array.isArray(body?.indices) ? body.indices.map(Number) : [];
    const degrees = Number(body?.degrees) || 90;
    const result = await engineOp({ op: 'rotatePages', indices, degrees });
    return { doc: result.doc };
  });

  defineApi('pdf.exportPagesPdf', 'user', async (body) => {
    const indices = Array.isArray(body?.indices) ? body.indices.map(Number) : [];
    let outPath = body?.path ? String(body.path) : '';
    if (!outPath) {
      const win = ownerWindow();
      const options = {
        title: '새 파일로 저장',
        filters: [{ name: 'PDF', extensions: ['pdf'] }],
        defaultPath: String(body?.defaultName || 'pages.pdf'),
      };
      const picked = win ? await dialog.showSaveDialog(win, options) : await dialog.showSaveDialog(options);
      if (picked.canceled || !picked.filePath) return { canceled: true };
      outPath = picked.filePath;
    }
    if (!outPath.toLowerCase().endsWith('.pdf')) outPath += '.pdf';
    await engineOp({ op: 'exportPagesPdf', indices, path: outPath });
    return { canceled: false, path: outPath };
  });

  defineApi('pdf.exportPagesImages', 'user', async (body) => {
    const indices = Array.isArray(body?.indices) ? body.indices.map(Number) : [];
    const folder = await pickImageFolder();
    if (!folder) return { canceled: true };
    const saved = await engineOp({
      op: 'exportPagesImages',
      indices,
      dir: folder,
      ...exportImageOptions(body?.options),
    });
    return {
      canceled: false,
      dir: saved.dir,
      files: saved.files ?? [],
      count: saved.files?.length ?? 0,
      stopped: Boolean(saved.stopped),
    };
  });

  defineApi('pdf.pageClipboard', 'user', async () => ({
    count: pageClipboard?.count || 0,
    hasPages: Boolean(pageClipboard?.pdf),
  }));

  defineApi('pdf.undo', 'user', async () => {
    const result = await engineOp({ op: 'undo' });
    return { doc: result.doc, changed: Boolean(result.changed) };
  });

  defineApi('pdf.redo', 'user', async () => {
    const result = await engineOp({ op: 'redo' });
    return { doc: result.doc, changed: Boolean(result.changed) };
  });

  /** 옵션창(ExportImagesDialog)에서 넘어온 값을 엔진 요청 형태로 맞춘다. */
  function exportImageOptions(raw) {
    const o = raw || {};
    return {
      dpi: Number(o.dpi) || 150,
      format: String(o.format || 'png'),
      jpegQuality: Number(o.jpegQuality) || 92,
      includeAnnotations: o.includeAnnotations !== false,
    };
  }

  /** 저장 폴더를 고른다. 취소되면 null. */
  async function pickImageFolder() {
    const win = ownerWindow();
    const pickOptions = { title: '이미지를 저장할 폴더 선택', properties: ['openDirectory', 'createDirectory'] };
    const picked = win ? await dialog.showOpenDialog(win, pickOptions) : await dialog.showOpenDialog(pickOptions);
    if (picked.canceled || !picked.filePaths[0]) return null;
    return picked.filePaths[0];
  }

  async function askMessage(options) {
    const win = ownerWindow();
    return win ? dialog.showMessageBox(win, options) : dialog.showMessageBox(options);
  }

  // 문서 전체 / 선택 범위 저장. 원본 _save_as_images: 옵션 → 폴더 → 덮어쓰기 확인 → 완료 후 폴더 열기.
  defineApi('pdf.exportImages', 'user', async (body) => {
    const options = body?.options || {};
    const parent = await pickImageFolder();
    if (!parent) return { canceled: true };
    const target = await engineOp({ op: 'exportImagesTarget', dir: parent });
    if (target.exists) {
      const reply = await askMessage({
        type: 'question',
        buttons: ['예', '아니요'],
        defaultId: 1,
        cancelId: 1,
        title: '이미지로 저장',
        message: `폴더가 이미 있습니다:\n${target.dir}`,
        detail: '기존 파일을 덮어쓸까요?',
      });
      if (reply.response !== 0) return { canceled: true };
    }
    const pageFrom = Math.max(1, Number(options.pageFrom) || 1);
    const pageTo = Number(options.pageTo) || undefined;
    const saved = await engineOp({
      op: 'exportImages',
      dir: target.dir,
      ...exportImageOptions(options),
      pageFrom,
      pageTo,
    });
    // 완료 질문(폴더 열기)을 띄우기 전에 진행 안내를 거둔다.
    for (const win of BrowserWindow.getAllWindows()) {
      if (!win.isDestroyed()) {
        win.webContents.send('pdf:log', { windowId: currentWindowId(), progress: { op: 'exportImages', done: true } });
      }
    }
    const stopped = Boolean(saved.stopped);
    const count = pageTo ? pageTo - pageFrom + 1 : null;
    const head = stopped
      ? '작업을 취소했습니다. 그때까지 저장된 이미지는 남아 있습니다.'
      : count
        ? `${count}개 이미지를 저장했습니다.`
        : '이미지를 저장했습니다.';
    const reply = await askMessage({
      type: 'question',
      buttons: ['예', '아니요'],
      defaultId: 0,
      cancelId: 1,
      title: '이미지로 저장',
      message: `${head}\n\n${saved.dir}`,
      detail: '폴더를 여시겠습니까?',
    });
    if (reply.response === 0) await shell.openPath(saved.dir);
    return { canceled: false, dir: saved.dir, count, stopped };
  });

  defineApi('pdf.search', 'user', async (body) => {
    const result = await engineOp({ op: 'search', query: String(body?.query || '') });
    return { hits: result.hits ?? [] };
  });

  defineApi('pdf.copyPages', 'user', async (body) => {
    const indices = Array.isArray(body?.indices) ? body.indices.map(Number) : [];
    const result = await engineOp({ op: 'extractPages', indices });
    pageClipboard = { pdf: result.pdf, count: result.count };
    return { count: result.count };
  });

  defineApi('pdf.cutPages', 'user', async (body) => {
    const indices = Array.isArray(body?.indices) ? body.indices.map(Number) : [];
    const result = await engineOp({ op: 'cutPages', indices });
    pageClipboard = { pdf: result.pdf, count: result.count };
    return { doc: result.doc, count: result.count };
  });

  defineApi('pdf.pastePages', 'user', async (body) => {
    if (!pageClipboard?.pdf) throw new ApiError('붙여넣을 페이지가 없습니다.');
    const index = Number.isInteger(body?.index) ? Number(body.index) : undefined;
    const result = await engineOp({ op: 'insertPages', pdf: pageClipboard.pdf, index });
    return { doc: result.doc, added: result.added };
  });

  defineApi('pdf.imageDpi', 'user', async () => {
    const result = await engineOp({ op: 'imageDpi' });
    return { dpi: Number.isFinite(result.dpi) ? result.dpi : null };
  });

  defineApi('pdf.reduceSize', 'user', async (body) => {
    const result = await engineOp({
      op: 'reduceSize',
      dpi: Number(body?.dpi) || 150,
      quality: Number(body?.quality) || 100,
      sizePercent: Number(body?.sizePercent) || 100,
    });
    if (result.stopped) return { stopped: true };
    return { doc: result.doc, before: result.before, after: result.after };
  });

  defineApi('pdf.pageNumbers', 'user', async (body) => {
    const result = await engineOp({ op: 'pageNumbers', options: body?.options || {} });
    return { doc: result.doc, changed: result.changed };
  });

  defineApi('pdf.pageNumberOptions', 'user', async () => {
    const result = await engineOp({ op: 'pageNumberOptions' });
    return { options: result.options ?? null };
  });

  defineApi('pdf.ocr', 'user', async (body) => {
    const result = await engineOp({
      op: 'ocr',
      mode: String(body?.mode || 'current'),
      index: Number(body?.index) || 0,
      indices: Array.isArray(body?.indices) ? body.indices.map(Number) : undefined,
    });
    return {
      stopped: Boolean(result.stopped),
      doc: result.doc,
      applied: result.applied,
      skipped: result.skipped,
      failed: result.failed,
      lines: result.lines,
    };
  });

  defineApi('pdf.setPassword', 'user', async (body) => {
    const result = await engineOp({
      op: 'setPassword',
      password: String(body?.password || ''),
      ownerPassword: body?.ownerPassword ? String(body.ownerPassword) : null,
    });
    return { doc: result.doc };
  });

  defineApi('pdf.clearPassword', 'user', async () => {
    const result = await engineOp({ op: 'clearPassword' });
    return { doc: result.doc };
  });

  defineApi('pdf.piiScan', 'user', async (body) => {
    const pageIndices = Array.isArray(body?.pageIndices)
      ? body.pageIndices.map((index) => Number(index)).filter((index) => Number.isInteger(index) && index >= 0)
      : null;
    const result = await engineOp({ op: 'piiScan', pageIndices });
    return {
      hits: result.hits ?? [],
      pagesScanned: result.pagesScanned,
      pagesWithoutText: result.pagesWithoutText,
      locatableCount: result.locatableCount,
      areaCount: result.areaCount ?? 0,
    };
  });

  defineApi('pdf.piiRedact', 'user', async (body) => {
    const result = await engineOp({
      op: 'piiRedact',
      hits: body?.hits || [],
      style: body?.style ? String(body.style) : undefined,
    });
    if (result.stopped) return { stopped: true };
    return { doc: result.doc, hitCount: result.hitCount, areaCount: result.areaCount };
  });

  /**
   * OS 클립보드에서 이미지 한 장을 읽는다. 없으면 null.
   * Electron 44+ clipboard.read() (Promise).
   * @returns {Promise<{ buffer: Buffer, mime: string } | null>}
   */
  async function readClipboardImage() {
    try {
      const items = await clipboard.read();
      for (const item of items) {
        const type = item.types.find((t) => t.startsWith('image/'));
        if (!type) continue;
        const blob = await item.getType(type);
        return { buffer: Buffer.from(await blob.arrayBuffer()), mime: type };
      }
    } catch {
      return null;
    }
    return null;
  }

  /** @param {string} mime */
  function imageExtForMime(mime) {
    const map = {
      'image/png': '.png',
      'image/jpeg': '.jpg',
      'image/jpg': '.jpg',
      'image/webp': '.webp',
      'image/gif': '.gif',
      'image/bmp': '.bmp',
      'image/tiff': '.tiff',
    };
    return map[String(mime || '').toLowerCase()] || '.png';
  }

  // 이미지 넣기: 클립보드 또는 파일에서 이미지를 읽어 base64 로 돌려준다.
  async function readImageToPlace(body) {
    if (body?.image) return { canceled: false, image: String(body.image) };
    if (body?.fromClipboard) {
      const clip = await readClipboardImage();
      if (!clip) throw new ApiError('클립보드에 이미지가 없습니다.');
      return { canceled: false, image: clip.buffer.toString('base64') };
    }
    const win = ownerWindow();
    const options = {
      title: '넣을 이미지 선택',
      filters: [{ name: '이미지', extensions: ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'tif', 'tiff', 'webp'] }],
      properties: ['openFile'],
    };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths[0]) return { canceled: true };
    return { canceled: false, image: fs.readFileSync(picked.filePaths[0]).toString('base64') };
  }

  /** 썸네일 우클릭 메뉴: OS 클립보드 이미지 여부와 내용 지문(쪽 복사 이후 새 이미지인지 판별). */
  defineApi('pdf.clipboardImageAvailable', 'user', async () => {
    const clip = await readClipboardImage();
    if (!clip?.buffer?.length) return { available: false, fingerprint: null };
    const fingerprint = createHash('sha1').update(clip.buffer).digest('hex');
    return { available: true, fingerprint };
  });

  /**
   * 썸네일 "여기에 붙여넣기": OS 클립보드 이미지를 새 쪽으로 삽입한다
   * (파일 드롭과 같이 이미지가 한 쪽이 된다).
   */
  defineApi('pdf.insertClipboardImage', 'user', async (body) => {
    const clip = await readClipboardImage();
    if (!clip) throw new ApiError('클립보드에 이미지가 없습니다.');
    const ext = imageExtForMime(clip.mime);
    const tempPath = path.join(os.tmpdir(), `tiny-neo-clip-${Date.now()}${ext}`);
    fs.writeFileSync(tempPath, clip.buffer);
    try {
      const index = Number.isInteger(body?.index) ? Number(body.index) : undefined;
      const result = await engineOp({
        op: 'insert',
        paths: [tempPath],
        index,
        passwords: {},
      });
      return { doc: result.doc, added: result.added, stopped: Boolean(result.stopped) };
    } finally {
      try {
        fs.unlinkSync(tempPath);
      } catch {
        /* ignore */
      }
    }
  });

  // 이미지 넣기: PDF 에 바로 넣지 않고, 미리보기(이동·크기 조절)용으로 이미지를 정리해 돌려준다.
  // 복사한 이미지를 붙여 넣을 때는 image(base64 원본)와 params/sizePt 를 직접 준다.
  defineApi('pdf.imagePrepare', 'user', async (body) => {
    const picked = await readImageToPlace(body);
    if (picked.canceled) return { canceled: true };
    const result = await engineOp({
      op: 'imagePrepare',
      pageIndex: Number(body?.pageIndex) || 0,
      image: picked.image,
      params: body?.params && typeof body.params === 'object' ? body.params : undefined,
      sizePt: Array.isArray(body?.sizePt) ? body.sizePt : undefined,
      rect: Array.isArray(body?.rect) ? body.rect : undefined,
    });
    return {
      canceled: false,
      token: result.token,
      preview: result.preview,
      previewWidth: result.previewWidth,
      previewHeight: result.previewHeight,
      params: result.params,
      aspect: result.aspect,
      rect: result.rect,
      page: result.page,
    };
  });

  // 보이는 모양(투명 배경·투명도·회전·자르기·색 보정)을 바꾼 미리보기
  defineApi('pdf.imagePreview', 'user', async (body) => {
    const result = await engineOp({
      op: 'imagePreview',
      token: body?.token ? String(body.token) : undefined,
      pageIndex: Number(body?.pageIndex) || 0,
      stampId: body?.id === undefined || body?.id === null ? undefined : Number(body.id),
      params: body?.params && typeof body.params === 'object' ? body.params : undefined,
      patch: body?.patch && typeof body.patch === 'object' ? body.patch : undefined,
    });
    return {
      preview: result.preview,
      previewWidth: result.previewWidth,
      previewHeight: result.previewHeight,
      params: result.params,
      aspect: result.aspect,
    };
  });

  defineApi('pdf.imageList', 'user', async (body) => {
    const result = await engineOp({
      op: 'imageList',
      pageIndex: body?.pageIndex === undefined || body?.pageIndex === null ? undefined : Number(body.pageIndex),
    });
    return { items: result.items || [] };
  });

  // 다시 편집하는 동안 해당 이미지를 쪽 화면에서 걷어낸다(편집 오버레이가 대신 보여 준다).
  defineApi('pdf.imageLift', 'user', async (body) => {
    await engineOp({
      op: 'imageLift',
      targets: Array.isArray(body?.targets) ? body.targets : [],
      lifted: Boolean(body?.lifted),
    });
    return {};
  });

  defineApi('pdf.imageCommit', 'user', async (body) => {
    const result = await engineOp({
      op: 'imageCommit',
      pageIndex: Number(body?.pageIndex) || 0,
      token: body?.token,
      rect: body?.rect,
      params: body?.params,
    });
    return { doc: result.doc, id: result.stampId };
  });

  // 이미 넣은 이미지의 위치·크기·모양 수정 (여러 개를 한 번에 → 실행 취소 한 단계)
  defineApi('pdf.imageUpdate', 'user', async (body) => {
    const result = await engineOp({
      op: 'imageUpdate',
      updates: Array.isArray(body?.updates) ? body.updates : [],
    });
    return { doc: result.doc, results: result.results || [] };
  });

  defineApi('pdf.imageDelete', 'user', async (body) => {
    const result = await engineOp({
      op: 'imageDelete',
      targets: Array.isArray(body?.targets) ? body.targets : [],
    });
    return { doc: result.doc, removed: Number(result.removed) || 0 };
  });

  // 복사·잘라내기·복제용: 원본 이미지 + 모양 + 쪽에서의 크기
  defineApi('pdf.imageSource', 'user', async (body) => {
    const result = await engineOp({
      op: 'imageSource',
      pageIndex: Number(body?.pageIndex) || 0,
      stampId: body?.id === undefined || body?.id === null ? undefined : Number(body.id),
      token: body?.token ? String(body.token) : undefined,
      params: body?.params && typeof body.params === 'object' ? body.params : undefined,
      rect: Array.isArray(body?.rect) ? body.rect : undefined,
    });
    return { image: result.image, params: result.params, sizePt: result.sizePt, rect: result.rect };
  });

  defineApi('pdf.imageApplyPages', 'user', async (body) => {
    const result = await engineOp({
      op: 'imageApplyPages',
      pageIndex: Number(body?.pageIndex) || 0,
      stampId: Number(body?.id), // 엔진 요청의 id 는 요청 번호 자리라 다른 이름을 쓴다
      pages: Array.isArray(body?.pages) ? body.pages : [],
    });
    return { doc: result.doc, pages: result.pages || [] };
  });

  defineApi('pdf.imageFlatten', 'user', async (body) => {
    const result = await engineOp({
      op: 'imageFlatten',
      pageIndex: Number(body?.pageIndex) || 0,
      stampId: Number(body?.id), // 엔진 요청의 id 는 요청 번호 자리라 다른 이름을 쓴다
      below: Boolean(body?.below),
    });
    return { doc: result.doc };
  });

  // 그리기: 쪽 화면 좌표(pt)의 획을 잉크 주석으로 넣는다. continueGroup 이면 바로 앞 그리기와 실행 취소 한 단계로 묶는다.
  defineApi('pdf.inkAdd', 'user', async (body) => {
    const result = await engineOp({
      op: 'inkAdd',
      pageIndex: Number(body?.pageIndex) || 0,
      strokes: Array.isArray(body?.strokes) ? body.strokes : [],
      color: Array.isArray(body?.color) ? body.color : [0.29, 0.29, 0.29],
      width: Number(body?.width) || 2,
      opacity: Number(body?.opacity) || 1,
      continueGroup: Boolean(body?.continueGroup),
    });
    return { doc: result.doc, added: Number(result.added) || 0 };
  });

  // 지우개: 이 앱이 그린 획 중 지우개 경로에 닿은 것만 지운다.
  defineApi('pdf.inkErase', 'user', async (body) => {
    const result = await engineOp({
      op: 'inkErase',
      pageIndex: Number(body?.pageIndex) || 0,
      path: Array.isArray(body?.path) ? body.path : [],
      radius: Number(body?.radius) || 6,
      continueGroup: Boolean(body?.continueGroup),
    });
    return { doc: result.doc, removed: Number(result.removed) || 0 };
  });

  // 선택 도구: 이 앱이 그린 잉크(펜·연필·형광펜) 목록. 쪽 화면 좌표의 strokes/rect 를 돌려준다.
  defineApi('pdf.inkList', 'user', async (body) => {
    const result = await engineOp({
      op: 'inkList',
      pageIndex: body?.pageIndex === undefined || body?.pageIndex === null ? undefined : Number(body.pageIndex),
    });
    return { items: result.items || [] };
  });

  defineApi('pdf.inkDelete', 'user', async (body) => {
    const result = await engineOp({
      op: 'inkDelete',
      pageIndex: Number(body?.pageIndex) || 0,
      inkId: Number(body?.inkId),
    });
    return { doc: result.doc };
  });

  defineApi('pdf.inkUpdate', 'user', async (body) => {
    const result = await engineOp({
      op: 'inkUpdate',
      pageIndex: Number(body?.pageIndex) || 0,
      inkId: Number(body?.inkId),
      strokes: Array.isArray(body?.strokes) ? body.strokes : [],
    });
    return { doc: result.doc, newId: Number(result.newId) || 0, changed: Boolean(result.changed) };
  });

  // 도형(선·화살표·사각형·타원·다각형·클라우드·폴리라인·텍스트 상자): 표준 주석으로 넣고, 나중에 다시 고친다.
  // 좌표는 쪽 화면 좌표(pt, 회전 반영). 점으로 그리는 도형은 points, 상자로 그리는 도형은 rect.
  function shapeGeometry(body) {
    return {
      points: Array.isArray(body?.points) ? body.points : undefined,
      rect: Array.isArray(body?.rect) ? body.rect : undefined,
    };
  }

  defineApi('pdf.shapeList', 'user', async (body) => {
    const result = await engineOp({
      op: 'shapeList',
      pageIndex: body?.pageIndex === undefined || body?.pageIndex === null ? undefined : Number(body.pageIndex),
    });
    return { items: result.items || [] };
  });

  defineApi('pdf.shapeAdd', 'user', async (body) => {
    const result = await engineOp({
      op: 'shapeAdd',
      pageIndex: Number(body?.pageIndex) || 0,
      kind: String(body?.kind || ''),
      ...shapeGeometry(body),
      params: body?.params && typeof body.params === 'object' ? body.params : {},
    });
    return { doc: result.doc, shapeId: result.shapeId };
  });

  // 위치(points/rect)나 모양(params)만 골라 보낼 수 있다. 고치면 주석이 새로 만들어져 id 가 바뀐다(newId).
  defineApi('pdf.shapeUpdate', 'user', async (body) => {
    const result = await engineOp({
      op: 'shapeUpdate',
      pageIndex: Number(body?.pageIndex) || 0,
      shapeId: Number(body?.shapeId),
      ...shapeGeometry(body),
      params: body?.params && typeof body.params === 'object' ? body.params : undefined,
    });
    return { doc: result.doc, newId: result.newId, changed: Boolean(result.changed) };
  });

  defineApi('pdf.shapeDelete', 'user', async (body) => {
    const result = await engineOp({
      op: 'shapeDelete',
      pageIndex: Number(body?.pageIndex) || 0,
      shapeId: Number(body?.shapeId),
    });
    return { doc: result.doc };
  });

  /* ---- 한글 → PDF (Tiny hwp_to_pdf_dialog.py 와 같은 규칙) ---- */

  /** 한컴 한글 설치 여부 (엔진을 띄워 확인하므로 한글 파일이 목록에 있을 때만 부른다). */
  defineApi('pdf.hwpAvailable', 'user', async () => {
    const windows = process.platform === 'win32';
    let installed = false;
    if (windows) {
      try {
        installed = Boolean((await engineOp({ op: 'hwpStatus' })).installed);
      } catch {
        installed = false;
      }
    }
    return { windows, installed };
  });

  /** 편집 화면에 한글 파일을 끌어다 놓았을 때: 임시 폴더로 바로 변환해 연다. */
  defineApi('pdf.hwpConvertQuick', 'user', async (body) => {
    const source = String(body?.source || '').trim();
    if (!source || !isHwpPath(source) || !fs.existsSync(source)) {
      throw new ApiError('HWP/HWPX 파일을 찾을 수 없습니다.');
    }
    // 임시 폴더에 변환 (사용자 상호작용 없음)
    const tempFolder = os.tmpdir();
    const stemName = path.basename(source, path.extname(source));
    const target = uniquePdfPath(tempFolder, stemName);
    const result = await engineOp({ op: 'hwpConvert', path: source, output: target });
    return { path: result.path };
  });

  /** 썸네일 드롭 등: TXT/MD/HTML 을 Chromium 으로 임시 PDF 로 바꾼다. */
  defineApi('pdf.textConvertQuick', 'user', async (body) => {
    const source = String(body?.source || '').trim();
    if (!source || !isTextPath(source) || !fs.existsSync(source)) {
      throw new ApiError('TXT/Markdown/JSON/HTML 파일을 찾을 수 없습니다.');
    }
    const target = await textConvertToTempPdf(source);
    return { path: target };
  });

  /**
   * "PDF 변환 > 개별 변환": 파일 하나를 PDF 하나로 바꾼다. 렌더러가 한 개씩 부르므로 진행 표시와 중지가 된다.
   *   - 한글(HWP/HWPX): 한컴 한글로 변환 (기존 hwpConvert)
   *   - 텍스트(TXT/MD/HTML): Chromium printToPDF (TXT·MD 실패 시 엔진 폴백)
   *   - 이미지: 병합 엔진에 파일 하나로 넘겨 한 쪽짜리 PDF 로 저장
   *   - PDF: 이미 PDF 라 변환할 것이 없다
   * 같은 이름이 있고 덮어쓰기가 아니면 "이름 (2).pdf" 식으로 피한다 (원본 _destination_for).
   */
  defineApi('pdf.convertOne', 'user', async (body) => {
    const source = String(body?.source || '').trim();
    if (!source || !fs.existsSync(source)) throw new ApiError('파일을 찾을 수 없습니다.');
    const ext = path.extname(source).toLowerCase();
    const isHwp = isHwpPath(source);
    const isText = isTextPath(source);
    if (ext === '.pdf') throw new ApiError('이미 PDF 파일입니다.');
    if (!isHwp && !MERGE_SUPPORTED_EXT.has(ext)) throw new ApiError('변환할 수 없는 파일 형식입니다.');

    const besideSource = Boolean(body?.besideSource);
    const folder = besideSource ? path.dirname(source) : String(body?.folder || '').trim();
    if (!folder || !isDirectory(folder)) throw new ApiError('유효한 저장 폴더를 지정해 주세요.');

    const stemName = path.basename(source, path.extname(source));
    const target = body?.overwrite
      ? path.join(folder, `${stemName}.pdf`)
      : uniquePdfPath(folder, stemName);
    let outPath;
    if (isHwp) {
      const result = await engineOp({ op: 'hwpConvert', path: source, output: target });
      outPath = result.path;
    } else if (isText) {
      outPath = await textFileToPdfPath(source, target);
    } else {
      const result = await engineOp({
        op: 'mergeFiles',
        paths: [source],
        output: target,
        passwords: {},
      });
      outPath = result.path;
    }

    // 저장 위치 기억: 병합과 같은 폴더 설정을 쓴다.
    const prev = readHwpPrefs();
    writeHwpPrefs({ besideSource, saveFolder: prev.saveFolder });
    if (!besideSource) writeMergeSaveFolder(folder);
    return { path: outPath };
  });

  // ---- 인쇄 ----
  // 인쇄 대화상자(렌더러)가 프린터 목록을 가져온다. 설치된 가상 프린터(Tiny PDF Editor)도 그대로 나온다.
  defineApi('pdf.printers', 'user', async () => {
    const win = ownerWindow();
    if (!win) return { printers: [] };
    const list = await win.webContents.getPrintersAsync();
    return {
      printers: list.map((item) => ({
        name: String(item.name),
        displayName: String(item.displayName || item.name),
        isDefault: Boolean(item.isDefault),
      })),
    };
  });

  // 대화상자에서 고른 설정대로 인쇄한다. 쪽을 높은 해상도로 그려 HTML 로 묶고, Chromium 이 프린터로 보낸다.
  // (Electron 은 PDF 뷰어 창을 그대로 인쇄하지 못해 — 빈 쪽이 나온다 — 그림 HTML 방식을 쓴다.)
  defineApi('pdf.printRun', 'user', async (body) => {
    const options = normalizePrintOptions(body?.options);
    if (!options.systemDialog && !options.printer) throw new ApiError('프린터를 선택해 주세요.');

    const sizes = (await engineOp({ op: 'pageSizes' })).sizes ?? [];
    const requested = Array.isArray(body?.indices) ? body.indices.map(Number) : sizes.map((_, i) => i);
    const indices = requested.filter((i) => Number.isInteger(i) && i >= 0 && i < sizes.length);
    if (!indices.length) throw new ApiError('인쇄할 쪽이 없습니다.');

    const layout = layoutSheets(indices.map((i) => sizes[i]), options);
    const dpi = dpiForSheets(layout.sheets.length);
    const cellByPosition = new Map();
    for (const sheet of layout.sheets) for (const cell of sheet.cells) cellByPosition.set(cell.i, cell);

    const work = fs.mkdtempSync(path.join(os.tmpdir(), 'tiny-neo-print-'));
    let printWin = null;
    try {
      const imageUrls = [];
      for (let position = 0; position < indices.length; position += 1) {
        const cell = cellByPosition.get(position);
        const written = await engineOp({
          op: 'printPage',
          index: indices[position],
          zoom: renderZoomFor(cell, sizes[indices[position]], dpi),
          path: path.join(work, `page-${position}`),
          gray: !options.color,
        });
        imageUrls.push(pathToFileURL(written.path).href);
      }
      const htmlPath = path.join(work, 'print.html');
      fs.writeFileSync(htmlPath, buildPrintHtml(layout, imageUrls), 'utf8');

      printWin = new BrowserWindow({
        show: false,
        webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false },
      });
      await printWin.loadFile(htmlPath);
      await printWin.webContents.executeJavaScript(
        "Promise.all([...document.images].map((img) => img.complete ? 1 : new Promise((done) => { img.onload = img.onerror = done; })))",
      );

      const printOptions = {
        silent: !options.systemDialog,
        printBackground: true,
        color: options.color,
        copies: options.copies,
        collate: options.collate,
        landscape: layout.electron.landscape,
        pageSize: layout.electron.pageSize,
        margins: { marginType: 'none' },
        duplexMode: options.duplex,
      };
      if (!options.systemDialog) printOptions.deviceName = options.printer;

      const outcome = await new Promise((resolve) => {
        printWin.webContents.print(printOptions, (success, reason) => resolve({ success, reason: String(reason || '') }));
      });
      if (!outcome.success) {
        if (/cancel/i.test(outcome.reason)) return { ok: false, canceled: true, sheets: layout.sheets.length };
        throw new ApiError(`인쇄하지 못했습니다.${outcome.reason ? ` (${outcome.reason})` : ''}`);
      }
      return { ok: true, canceled: false, sheets: layout.sheets.length, pages: indices.length };
    } finally {
      if (printWin && !printWin.isDestroyed()) printWin.destroy();
      try {
        fs.rmSync(work, { recursive: true, force: true });
      } catch {
        /* 임시 폴더 정리는 실패해도 인쇄 결과에 영향이 없다 */
      }
    }
  });

  // 파일 연결은 엔진이 아니라 이 앱(Neo) 실행 파일을 가리켜야 하므로 실행 명령을 함께 넘긴다.
  const assocLauncher = () => ({ exe: appLauncher().exe, command: launcherCommand() });
  defineApi('pdf.assocStatus', 'user', async () => engineOp({ op: 'assocStatus', launcher: assocLauncher() }));
  defineApi('pdf.assocRegister', 'user', async (body) =>
    engineOp({
      op: 'assocRegister',
      openSettings: Boolean(body?.openSettings ?? true),
      launcher: assocLauncher(),
    }),
  );
  defineApi('pdf.assocUnregister', 'user', async () =>
    engineOp({ op: 'assocUnregister', launcher: assocLauncher() }),
  );

  // 가상 프린터: 설치·제거·감시 등록은 엔진(Python) 없이 앱이 직접 한다. (printService.js)
  defineApi('pdf.printerStatus', 'user', async () => ({
    supported: printerSupported(),
    installed: printerSupported() ? printerInstalled() : false,
  }));
  defineApi('pdf.printerInstall', 'user', async () => {
    await enablePrinter();
    return { installed: true };
  });
  defineApi('pdf.printerUninstall', 'user', async () => {
    await disablePrinter();
    return { installed: false };
  });
}
