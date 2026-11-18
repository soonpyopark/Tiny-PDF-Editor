/**
 * 가상 프린터 스풀 계약 (Electron 에 의존하지 않는 순수 Node 모듈).
 *
 * 앱(main process)과 가벼운 백그라운드 감시자(print-watch.mjs, ELECTRON_RUN_AS_NODE)가
 * 같은 코드를 쓰도록 한 곳에 둔다. 값과 타이밍은 기존 Tiny 인쇄 계약 그대로다.
 *
 *   프린터 "Tiny PDF Editor"(드라이버 Microsoft Print To PDF)의 파일 포트
 *     = %LOCALAPPDATA%\Tiny PDF Editor\print-spool\tiny-print.pdf
 *   감시자: 파일이 %PDF- 로 시작하고 쓰기용으로 열리면(=인쇄 완료)
 *     다운로드 폴더로 "Tiny 인쇄 <yymmdd_HHMMSS>[_n].pdf" 로 옮기고 에디터를 연다.
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const PRINTER_NAME = 'Tiny PDF Editor';
export const RUN_VALUE_NAME = 'TinyPDFEditorPrintWatch';
export const WATCH_FLAG = '--print-watch';

const SPOOL_VENDOR_DIR = 'Tiny PDF Editor';
const SPOOL_FILE_NAME = 'tiny-print.pdf';
const LOCK_FILE_NAME = 'print-watch.lock';

/** 감시 타이밍 (원본과 같다). */
const POLL_MS = 800;
const DEBOUNCE_MS = 1200;
const RETRY_MS = 500;
const RETRY_MAX = 40;
/** 감시자는 폴링마다 락 파일을 갱신한다. 이 시간 넘게 갱신이 없으면 죽은 락으로 본다. */
const LOCK_STALE_MS = 10_000;

const isWindows = process.platform === 'win32';

/* -------------------------------------------------------------------------- */
/* paths                                                                      */
/* -------------------------------------------------------------------------- */

function localAppData() {
  return process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
}

/** 테스트용으로 TINY_PRINT_SPOOL_DIR 로 바꿀 수 있다. 기본값은 원본과 같은 위치. */
export function spoolDir() {
  const override = String(process.env.TINY_PRINT_SPOOL_DIR ?? '').trim();
  if (override) return path.resolve(override);
  return path.join(localAppData(), SPOOL_VENDOR_DIR, 'print-spool');
}

export function spoolFile() {
  return path.join(spoolDir(), SPOOL_FILE_NAME);
}

export function watchLockFile() {
  return path.join(spoolDir(), LOCK_FILE_NAME);
}

let cachedDownloads = '';

/** Windows "다운로드" 알려진 폴더. 읽지 못하면 ~/Downloads. */
function downloadsDir() {
  if (cachedDownloads) return cachedDownloads;
  let found = '';
  if (isWindows) {
    const reg = spawnSync(
      'reg.exe',
      [
        'query',
        'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders',
        '/v',
        '{374DE290-123F-4565-9164-ACA76A8DD45B}',
      ],
      { windowsHide: true, encoding: 'utf8' },
    );
    if (reg.status === 0) {
      const match = /REG_(?:EXPAND_)?SZ\s+(.+?)\s*$/m.exec(reg.stdout ?? '');
      if (match) {
        found = match[1].replace(/%([^%]+)%/g, (whole, name) => process.env[name] ?? whole);
      }
    }
  }
  cachedDownloads = found && fs.existsSync(path.dirname(found)) ? found : path.join(os.homedir(), 'Downloads');
  return cachedDownloads;
}

export function outputDir() {
  const override = String(process.env.TINY_PRINT_OUTPUT_DIR ?? '').trim();
  return override ? path.resolve(override) : downloadsDir();
}

/* -------------------------------------------------------------------------- */
/* printer                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * 가상 프린터가 이 PC에 설치돼 있는지. 레지스트리의 프린터 키로 판단한다
 * (PowerShell 보다 훨씬 빠르다). 테스트에서는 TINY_PRINT_ASSUME_INSTALLED=1.
 */
export function printerInstalled() {
  if (process.env.TINY_PRINT_ASSUME_INSTALLED === '1') return true;
  if (!isWindows) return false;
  const reg = spawnSync(
    'reg.exe',
    ['query', `HKLM\\SYSTEM\\CurrentControlSet\\Control\\Print\\Printers\\${PRINTER_NAME}`],
    { windowsHide: true, encoding: 'utf8' },
  );
  return reg.status === 0;
}

/* -------------------------------------------------------------------------- */
/* claim                                                                      */
/* -------------------------------------------------------------------------- */

function pad(value) {
  return String(value).padStart(2, '0');
}

/** `Tiny 인쇄 yymmdd_HHMMSS[_n].pdf` — 같은 초에 두 건이면 _2, _3 … */
export function nextOutputPdf(now = new Date()) {
  const stamp =
    `${pad(now.getFullYear() % 100)}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const folder = outputDir();
  fs.mkdirSync(folder, { recursive: true });
  let candidate = path.join(folder, `Tiny 인쇄 ${stamp}.pdf`);
  let index = 2;
  while (fs.existsSync(candidate)) {
    candidate = path.join(folder, `Tiny 인쇄 ${stamp}_${index}.pdf`);
    index += 1;
  }
  return candidate;
}

/**
 * 인쇄가 끝났는지: 8바이트 이상, `%PDF-` 로 시작, 그리고 쓰기용으로 열린다
 * (드라이버가 아직 잡고 있으면 열리지 않는다).
 * @param {string} file
 */
export function fileIsReady(file) {
  let size;
  try {
    const stat = fs.statSync(file);
    if (!stat.isFile()) return false;
    size = stat.size;
  } catch {
    return false;
  }
  if (size < 8) return false;
  let fd;
  try {
    fd = fs.openSync(file, 'r+');
    const head = Buffer.alloc(5);
    const read = fs.readSync(fd, head, 0, 5, 0);
    return read === 5 && head.toString('latin1') === '%PDF-';
  } catch {
    return false;
  } finally {
    if (fd !== undefined) {
      try {
        fs.closeSync(fd);
      } catch {
        // 닫기 실패는 무시한다.
      }
    }
  }
}

/**
 * 스풀 PDF 를 다운로드 폴더로 가져온다. 아직 인쇄 중이거나 파일이 없으면 null.
 * @returns {string | null}
 */
export function claimSpoolPdf() {
  const source = spoolFile();
  if (!fileIsReady(source)) return null;
  const dest = nextOutputPdf();
  try {
    fs.renameSync(source, dest);
  } catch {
    try {
      fs.copyFileSync(source, dest);
      fs.rmSync(source, { force: true });
    } catch {
      return null;
    }
  }
  return fs.existsSync(dest) ? dest : null;
}

/* -------------------------------------------------------------------------- */
/* single-watcher lock                                                        */
/* -------------------------------------------------------------------------- */

function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === 'EPERM';
  }
}

function readLock() {
  try {
    const file = watchLockFile();
    const pid = Number.parseInt(fs.readFileSync(file, 'utf8').split(/\r?\n/)[0], 10);
    const { mtimeMs } = fs.statSync(file);
    return { pid, mtimeMs };
  } catch {
    return null;
  }
}

/** 다른(또는 이) 프로세스의 감시자가 살아 있는지. */
export function watcherRunning() {
  const lock = readLock();
  if (!lock) return false;
  return pidAlive(lock.pid) && Date.now() - lock.mtimeMs < LOCK_STALE_MS;
}

/** 락 주인(감시자) 프로세스 id. 살아 있는 감시자가 없으면 0. */
export function watcherPid() {
  const lock = readLock();
  if (!lock) return 0;
  return pidAlive(lock.pid) && Date.now() - lock.mtimeMs < LOCK_STALE_MS ? lock.pid : 0;
}

/**
 * 락을 잡는다. 이미 살아 있는 다른 감시자가 있으면 false.
 * 주인 프로세스가 죽었거나 갱신이 끊긴 락은 빼앗는다.
 */
function acquireLock() {
  fs.mkdirSync(spoolDir(), { recursive: true });
  const file = watchLockFile();
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      fs.writeFileSync(file, `${process.pid}\n`, { flag: 'wx' });
      return true;
    } catch (error) {
      if (error?.code !== 'EEXIST') return false;
    }
    const lock = readLock();
    if (lock && pidAlive(lock.pid) && Date.now() - lock.mtimeMs < LOCK_STALE_MS) {
      return false;
    }
    try {
      fs.rmSync(file, { force: true });
    } catch {
      return false;
    }
  }
  return false;
}

function releaseLock() {
  const lock = readLock();
  if (lock && lock.pid === process.pid) {
    try {
      fs.rmSync(watchLockFile(), { force: true });
    } catch {
      // 다음 감시자가 죽은 락으로 보고 치운다.
    }
  }
}

/** 내가 아직 락 주인인지 확인하고 갱신한다. 뺏겼으면 false. */
function renewLock() {
  const lock = readLock();
  if (!lock || lock.pid !== process.pid) return false;
  try {
    const now = new Date();
    fs.utimesSync(watchLockFile(), now, now);
  } catch {
    // 갱신 실패는 다음 틱에 다시 시도한다.
  }
  return true;
}

/* -------------------------------------------------------------------------- */
/* watcher                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * 스풀 폴더를 감시한다. 락을 못 잡으면(다른 감시자가 있으면) null.
 *
 * @param {{ onPdf: (file: string) => void, onLockLost?: () => void, log?: (message: string) => void }} options
 * @returns {{ stop: () => void } | null}
 */
export function startSpoolWatcher({ onPdf, onLockLost, log = () => undefined }) {
  if (!acquireLock()) return null;

  let retries = 0;
  /** @type {NodeJS.Timeout | null} */
  let debounce = null;
  /** @type {NodeJS.Timeout | null} */
  let retry = null;
  let stopped = false;

  const clearRetry = () => {
    if (retry) clearInterval(retry);
    retry = null;
  };

  /** 직전 관찰 때의 스풀 파일 크기. 드라이버가 아직 쓰는 중이면 크기가 계속 변한다. */
  let lastSize = -1;

  const tryClaim = () => {
    if (stopped) return;
    let claimed = null;
    try {
      let size = -1;
      try {
        size = fs.statSync(spoolFile()).size;
      } catch {
        size = -1;
      }
      // 크기가 직전 관찰과 같을 때만 가져간다. 쓰는 도중의 부분 파일을 열지 않기 위한 안전장치다.
      const settled = size >= 0 && size === lastSize;
      lastSize = size;
      if (settled) claimed = claimSpoolPdf();
    } catch (error) {
      log(`claim failed: ${error?.message ?? error}`);
    }
    if (claimed) {
      clearRetry();
      retries = 0;
      log(`claimed ${claimed}`);
      try {
        onPdf(claimed);
      } catch (error) {
        log(`onPdf failed: ${error?.message ?? error}`);
      }
      return;
    }
    if (!claimed && fs.existsSync(spoolFile())) {
      retries += 1;
      if (retries <= RETRY_MAX) {
        if (!retry) retry = setInterval(tryClaim, RETRY_MS);
      } else {
        clearRetry();
      }
    }
  };

  const onChange = () => {
    retries = 0;
    clearRetry();
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(tryClaim, DEBOUNCE_MS);
  };

  /** @type {fs.FSWatcher | null} */
  let watcher = null;
  try {
    watcher = fs.watch(spoolDir(), { persistent: true }, onChange);
    watcher.on('error', () => undefined);
  } catch (error) {
    // 감시 실패해도 아래 폴링이 같은 일을 한다.
    log(`fs.watch unavailable: ${error?.message ?? error}`);
  }

  const poll = setInterval(() => {
    if (stopped) return;
    if (!renewLock()) {
      stop();
      onLockLost?.();
      return;
    }
    tryClaim();
  }, POLL_MS);

  function stop() {
    if (stopped) return;
    stopped = true;
    clearInterval(poll);
    clearRetry();
    if (debounce) clearTimeout(debounce);
    try {
      watcher?.close();
    } catch {
      // 이미 닫혔다.
    }
    releaseLock();
  }

  tryClaim();
  return { stop };
}

/* -------------------------------------------------------------------------- */
/* launch                                                                     */
/* -------------------------------------------------------------------------- */

/** 자식에게 ELECTRON_RUN_AS_NODE 가 새지 않도록 지운 환경. */
export function cleanEnv() {
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  return env;
}

/**
 * 에디터(앱)를 띄운다. 이미 떠 있으면 second-instance 로 경로가 넘어간다.
 * @param {{ exe: string, prefixArgs?: string[], pdfPath?: string }} options
 */
export function launchEditor({ exe, prefixArgs = [], pdfPath = '' }) {
  const args = [...prefixArgs, ...(pdfPath ? [pdfPath] : [])];
  // e2e/진단: env 만으로는 Chromium 이 포트를 못 여는 경우가 있어 CLI 로도 넘긴다.
  const debugPort = String(process.env.TINY_DEBUG_PORT || '').trim();
  if (debugPort) args.unshift(`--remote-debugging-port=${debugPort}`);
  const child = spawn(exe, args, {
    detached: true,
    stdio: 'ignore',
    env: cleanEnv(),
    windowsHide: false,
  });
  child.on('error', () => undefined);
  child.unref();
}
