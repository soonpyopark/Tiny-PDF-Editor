/**
 * Local bridge to Tiny PDF Editor's Python engine (pdf_editor.engine).
 * The engine is a child process on this PC. It is not exposed as its own port.
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';
import { BrowserWindow, clipboard, dialog, shell } from 'electron';
import { ApiError, currentWindowId, defineApi } from '../api/registry.js';

// neo-app/electron/modules/ 기준 두 단계 위가 Tiny PDF Editor - neo 루트(pdf_editor 패키지가 있는 곳).
const engineRoot =
  process.env.TINY_PDF_ROOT ||
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

const OPEN_FILTERS = [
  { name: 'PDF', extensions: ['pdf'] },
  { name: '이미지', extensions: ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'tif', 'tiff', 'webp'] },
  { name: '한글', extensions: ['hwp', 'hwpx'] },
];

const RECENT_LIMIT = 12;
const recentPath = path.join(os.homedir(), '.tiny-pdf-editor-neo', 'recent.json');

/** @type {{ cmd: string, prefix: string[] } | null} */
let pythonCommand = null;
/**
 * 창(windowId)마다 엔진 자식 프로세스 하나와 요청 큐를 가진다.
 * 한 창의 문서가 다른 창의 문서와 섞이지 않도록 나눈다.
 * @type {Map<string, { windowId: string, child: import('node:child_process').ChildProcess | null, pending: Map<number, { resolve: (msg: any) => void, reject: (err: Error) => void }>, chain: Promise<unknown>, seq: number, stderrTail: string }>}
 */
const sessions = new Map();
/** @type {{ pdf: string, count: number } | null} */
let pageClipboard = null;

const SLOW_OPS = new Set([
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
  '.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.hwp', '.hwpx',
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
  const python = resolvePython();
  session.stderrTail = '';
  const child = spawn(python.cmd, [...python.prefix, '-u', '-m', 'pdf_editor.engine'], {
    cwd: engineRoot,
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1',
      QT_QPA_PLATFORM: 'offscreen',
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
  const session = sessions.get(windowId);
  if (!session) return;
  sessions.delete(windowId);
  failPending(session, new ApiError('창이 닫혀 PDF 엔진을 종료했습니다.'));
  if (session.child && session.child.exitCode == null) session.child.kill();
  session.child = null;
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
  const opened = await engineOp({
    op: 'open',
    path: filePath,
    password: password ? String(password) : null,
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
}

export function register() {
  defineApi('pdf.status', 'user', async () => {
    try {
      resolvePython();
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
      filters: OPEN_FILTERS,
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
      filters: OPEN_FILTERS,
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
      let filters = OPEN_FILTERS;
      if (body?.filters === 'all') {
        filters = [{ name: '전체', extensions: ['*'] }, ...OPEN_FILTERS];
      }
      const options = {
        title: '페이지 추가',
        filters,
        properties: ['openFile', 'multiSelections'],
      };
      const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
      if (picked.canceled || !picked.filePaths.length) return { canceled: true };
      paths = picked.filePaths;
    }
    const index = Number.isInteger(body?.index) ? Number(body.index) : undefined;
    const result = await engineOp({ op: 'insert', paths, index });
    return { canceled: false, doc: result.doc, added: result.added };
  });

  defineApi('pdf.mergeState', 'user', async () => ({ saveFolder: readMergeSaveFolder() }));

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
    const result = await engineOp({
      op: 'previewFile',
      path: filePath,
      password: body?.password ? String(body.password) : null,
    });
    if (result.needsPassword) return { needsPassword: true, rejected: Boolean(result.rejected) };
    if (result.unsupported) return { unsupported: true };
    return { png: result.png, width: result.width, height: result.height, pageCount: result.pageCount };
  });

  defineApi('pdf.mergeRun', 'user', async (body) => {
    const paths = Array.isArray(body?.paths) ? body.paths.map(String).filter(Boolean) : [];
    if (!paths.length) throw new ApiError('병합할 파일이 없습니다.');
    const folder = String(body?.folder || '').trim();
    if (!folder || !isDirectory(folder)) throw new ApiError('유효한 저장 폴더를 지정해 주세요.');
    const target = path.join(folder, `${sanitizeMergeName(body?.name)}.pdf`);
    if (fs.existsSync(target) && !body?.overwrite) return { exists: true, target };

    const merged = await engineOp({
      op: 'mergeFiles',
      paths,
      output: target,
      passwords: passwordMap(body?.passwords),
    });
    if (merged.needsPassword) {
      return { needsPassword: true, path: merged.path, rejected: Boolean(merged.rejected) };
    }
    writeMergeSaveFolder(folder);
    return { canceled: false, path: merged.path, pages: merged.pages, added: merged.added };
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
    const merged = await engineOp({ op: 'merge', paths: picked.filePaths });
    return { canceled: false, doc: merged.doc, added: merged.added };
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
    return { canceled: false, dir: saved.dir, files: saved.files ?? [], count: saved.files?.length ?? 0 };
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
    const count = pageTo ? pageTo - pageFrom + 1 : null;
    const head = count ? `${count}개 이미지를 저장했습니다.` : '이미지를 저장했습니다.';
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
    return { canceled: false, dir: saved.dir, count };
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

  defineApi('pdf.reduceSize', 'user', async (body) => {
    const result = await engineOp({
      op: 'reduceSize',
      dpi: Number(body?.dpi) || 150,
      quality: Number(body?.quality) || 100,
      sizePercent: Number(body?.sizePercent) || 100,
    });
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
    return { doc: result.doc, hitCount: result.hitCount, areaCount: result.areaCount };
  });

  defineApi('pdf.stampImage', 'user', async (body) => {
    let image = body?.image ? String(body.image) : '';
    if (!image && body?.fromClipboard) {
      const clip = clipboard.readImage();
      if (clip.isEmpty()) throw new ApiError('클립보드에 이미지가 없습니다.');
      image = clip.toPNG().toString('base64');
    }
    if (!image && body?.pickFile) {
      const win = ownerWindow();
      const options = {
        title: '서명 이미지 선택',
        filters: [{ name: '이미지', extensions: ['png', 'jpg', 'jpeg', 'bmp', 'webp'] }],
        properties: ['openFile'],
      };
      const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
      if (picked.canceled || !picked.filePaths[0]) return { canceled: true };
      image = fs.readFileSync(picked.filePaths[0]).toString('base64');
    }
    if (!image) throw new ApiError('서명 이미지가 없습니다.');
    const result = await engineOp({
      op: 'stampImage',
      pageIndex: Number(body?.pageIndex) || 0,
      image,
      rect: body?.rect || null,
    });
    return { canceled: false, doc: result.doc };
  });

  /* ---- 한글 → PDF (Tiny hwp_to_pdf_dialog.py 와 같은 규칙) ---- */

  defineApi('pdf.hwpState', 'user', async () => {
    const prefs = readHwpPrefs();
    const windows = process.platform === 'win32';
    let installed = false;
    if (windows) {
      try {
        installed = Boolean((await engineOp({ op: 'hwpStatus' })).installed);
      } catch {
        installed = false;
      }
    }
    return { windows, installed, besideSource: prefs.besideSource, saveFolder: prefs.saveFolder };
  });

  defineApi('pdf.hwpPickFiles', 'user', async () => {
    const win = ownerWindow();
    const options = {
      title: '한글 문서 선택',
      filters: [
        { name: '한글 문서', extensions: ['hwp', 'hwpx'] },
        { name: '모든 파일', extensions: ['*'] },
      ],
      properties: ['openFile', 'multiSelections'],
    };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths.length) return { canceled: true, paths: [] };
    return { canceled: false, paths: picked.filePaths.filter(isHwpPath) };
  });

  defineApi('pdf.hwpPickFolder', 'user', async () => {
    const win = ownerWindow();
    const options = { title: '한글 문서가 있는 폴더 선택', properties: ['openDirectory'] };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths[0]) return { canceled: true, paths: [] };
    const folder = picked.filePaths[0];
    const paths = fs
      .readdirSync(folder, { withFileTypes: true })
      .filter((entry) => entry.isFile() && isHwpPath(entry.name))
      .map((entry) => path.join(folder, entry.name))
      .sort();
    return { canceled: false, paths };
  });

  defineApi('pdf.hwpPickSaveFolder', 'user', async () => {
    const win = ownerWindow();
    const options = { title: '저장 폴더 선택', properties: ['openDirectory', 'createDirectory'] };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    if (picked.canceled || !picked.filePaths[0]) return { canceled: true };
    return { canceled: false, folder: picked.filePaths[0] };
  });

  /**
   * 파일 하나를 PDF로 바꾼다. 렌더러가 한 개씩 부르므로 진행 표시와 중지가 된다.
   * 같은 이름이 있고 덮어쓰기가 아니면 "이름 (2).pdf" 식으로 피한다 (원본 _destination_for).
   */
  defineApi('pdf.hwpConvertOne', 'user', async (body) => {
    const source = String(body?.source || '').trim();
    if (!source || !isHwpPath(source) || !fs.existsSync(source)) {
      throw new ApiError('HWP/HWPX 파일을 찾을 수 없습니다.');
    }
    const besideSource = Boolean(body?.besideSource);
    const folder = besideSource ? path.dirname(source) : String(body?.folder || '').trim();
    if (!folder || !isDirectory(folder)) throw new ApiError('유효한 저장 폴더를 지정해 주세요.');

    const stemName = path.basename(source, path.extname(source));
    const target = body?.overwrite
      ? path.join(folder, `${stemName}.pdf`)
      : uniquePdfPath(folder, stemName);
    const result = await engineOp({ op: 'hwpConvert', path: source, output: target });

    const prev = readHwpPrefs();
    writeHwpPrefs({ besideSource, saveFolder: besideSource ? prev.saveFolder : folder });
    return { path: result.path };
  });

  defineApi('pdf.print', 'user', async (body) => {
    const win = ownerWindow();
    const target = body?.path ? String(body.path) : '';
    const indices = Array.isArray(body?.indices) ? body.indices.map(Number) : [];
    let pdfPath = target;
    if (!pdfPath && indices.length) {
      pdfPath = path.join(os.tmpdir(), `tiny-neo-print-pages-${Date.now()}.pdf`);
      await engineOp({ op: 'exportPagesPdf', indices, path: pdfPath });
    } else if (!pdfPath) {
      const tmp = path.join(os.tmpdir(), `tiny-neo-print-${Date.now()}.pdf`);
      const saved = await engineOp({ op: 'save', path: tmp });
      pdfPath = saved.path || tmp;
    }
    if (process.platform === 'win32') {
      spawn('cmd', ['/c', 'start', '', '/print', pdfPath], { windowsHide: true, detached: true, stdio: 'ignore' }).unref();
      return { ok: true, path: pdfPath };
    }
    if (win) {
      await win.webContents.print({ silent: false, printBackground: true });
      return { ok: true, path: pdfPath };
    }
    await shell.openPath(pdfPath);
    return { ok: true, path: pdfPath };
  });

  defineApi('pdf.assocStatus', 'user', async () => engineOp({ op: 'assocStatus' }));
  defineApi('pdf.assocRegister', 'user', async (body) =>
    engineOp({ op: 'assocRegister', openSettings: Boolean(body?.openSettings ?? true) }),
  );
  defineApi('pdf.assocUnregister', 'user', async () => engineOp({ op: 'assocUnregister' }));
  defineApi('pdf.printerStatus', 'user', async () => engineOp({ op: 'printerStatus' }));
  defineApi('pdf.printerInstall', 'user', async () => engineOp({ op: 'printerInstall' }));
  defineApi('pdf.printerUninstall', 'user', async () => engineOp({ op: 'printerUninstall' }));
}
