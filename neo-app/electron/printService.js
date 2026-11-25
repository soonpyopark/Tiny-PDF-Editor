/**
 * 가상 프린터 + 인쇄 스풀 감시 (Windows).
 *
 * 계약(제1원칙 — 회귀 금지): 다른 앱에서 「Tiny PDF Editor」 프린터로 인쇄하면
 *   · 앱이 켜져 있든, 꺼져 있든, 방금 종료했든 그 PDF 가 에디터에 열린다.
 * 이를 위해 감시자는 앱과 별개의 가벼운 백그라운드 프로세스(print-watch.mjs)이고,
 * 앱을 종료해도 계속 살아 있다. 앱은 시작할 때마다 감시자가 있는지 확인해 없으면 띄운다.
 * 로그인 때는 HKCU Run 값(TinyPDFEditorPrintWatch)이 `<앱> --print-watch` 로 감시자를 띄운다.
 *
 * 테스트 전용 환경 변수 (일반 사용에서는 쓰지 않는다):
 *   TINY_PRINT_SPOOL_DIR / TINY_PRINT_OUTPUT_DIR / TINY_PRINT_ASSUME_INSTALLED  (printSpool.mjs)
 *   TINY_PRINT_PREFS_DIR   프린터 사용 여부 설정 파일 위치
 *   TINY_PRINT_NO_REGISTRY=1   Run 키를 읽고 쓰지 않는다
 *   TINY_PRINT_NO_AUTOINSTALL=1   첫 실행 자동 설치를 하지 않는다
 *   TINY_PRINT_DEV=1   개발 실행(!app.isPackaged)에서도 인쇄 서비스를 켠다
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { app } from 'electron';
import {
  PRINTER_NAME,
  RUN_VALUE_NAME,
  WATCH_FLAG,
  cleanEnv,
  launchEditor,
  printerInstalled,
  spoolDir,
  spoolFile,
  startSpoolWatcher,
  watcherPid,
  watcherRunning,
} from './print/printSpool.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const isWindows = process.platform === 'win32';
const PRINTER_DRIVER = 'Microsoft Print To PDF';
const RUN_KEY = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run';

export { WATCH_FLAG, printerInstalled };

function log(...args) {
  console.log('[print]', ...args);
}

/** 이 환경에서 가상 프린터를 쓸 수 있는지. (macOS 는 아직 Neo 에 이식되지 않았다.) */
export function printerSupported() {
  return isWindows;
}

/** 인쇄 서비스를 켤지. 개발 실행에서는 시스템(레지스트리/프로세스)을 건드리지 않는다. */
function serviceEnabled() {
  return isWindows && (app.isPackaged || process.env.TINY_PRINT_DEV === '1');
}

/* -------------------------------------------------------------------------- */
/* launcher                                                                   */
/* -------------------------------------------------------------------------- */

/** 이 앱을 다시 띄우는 방법. 개발 실행은 `electron <앱 폴더>` 다. */
export function launcher() {
  return {
    exe: process.execPath,
    prefixArgs: app.isPackaged ? [] : [app.getAppPath()],
  };
}

function quote(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}

/** 파일 연결·Run 키에 쓰는 명령 앞부분. 예: `"C:\...\Tiny PDF Editor.exe"` */
export function launcherCommand() {
  const { exe, prefixArgs } = launcher();
  return [quote(exe), ...prefixArgs.map(quote)].join(' ');
}

function watchScriptPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'print', 'print-watch.mjs')
    : path.join(here, 'print', 'print-watch.mjs');
}

/* -------------------------------------------------------------------------- */
/* prefs (virtualPrinterEnabled: true | false | null)                         */
/* -------------------------------------------------------------------------- */

function prefsFile() {
  const dir = String(process.env.TINY_PRINT_PREFS_DIR ?? '').trim() || path.join(os.homedir(), '.tiny-pdf-editor-neo');
  return path.join(dir, 'print.json');
}

/** @returns {boolean | null} null = 아직 한 번도 정하지 않음(첫 실행). */
export function readPrinterPref() {
  try {
    const value = JSON.parse(fs.readFileSync(prefsFile(), 'utf8'))?.virtualPrinterEnabled;
    return typeof value === 'boolean' ? value : null;
  } catch {
    return null;
  }
}

export function writePrinterPref(enabled) {
  try {
    fs.mkdirSync(path.dirname(prefsFile()), { recursive: true });
    fs.writeFileSync(prefsFile(), JSON.stringify({ virtualPrinterEnabled: Boolean(enabled) }, null, 2));
  } catch (error) {
    log('prefs write failed:', error?.message ?? error);
  }
}

/* -------------------------------------------------------------------------- */
/* logon watcher (HKCU Run)                                                   */
/* -------------------------------------------------------------------------- */

function watchCommand() {
  return `${launcherCommand()} ${WATCH_FLAG}`;
}

/** 로그인 때 백그라운드 감시자를 띄우는 Run 값을 켜거나 끈다. */
export function setWatchAtLogon(enabled) {
  if (!isWindows || process.env.TINY_PRINT_NO_REGISTRY === '1') return false;
  const args = enabled
    ? ['add', RUN_KEY, '/v', RUN_VALUE_NAME, '/t', 'REG_SZ', '/d', watchCommand(), '/f']
    : ['delete', RUN_KEY, '/v', RUN_VALUE_NAME, '/f'];
  const result = spawnSync('reg.exe', args, { windowsHide: true, encoding: 'utf8' });
  if (result.status !== 0 && enabled) {
    log('Run key write failed:', (result.stderr || result.stdout || '').trim());
  }
  return result.status === 0;
}

/** 현재 등록된 Run 값(없으면 ''). */
export function readWatchAtLogon() {
  if (!isWindows || process.env.TINY_PRINT_NO_REGISTRY === '1') return '';
  const result = spawnSync('reg.exe', ['query', RUN_KEY, '/v', RUN_VALUE_NAME], {
    windowsHide: true,
    encoding: 'utf8',
  });
  if (result.status !== 0) return '';
  const match = /REG_SZ\s+(.+?)\s*$/m.exec(result.stdout ?? '');
  return match ? match[1] : '';
}

/* -------------------------------------------------------------------------- */
/* background watcher process                                                 */
/* -------------------------------------------------------------------------- */

/**
 * 감시자가 없으면 띄운다. 이미 있으면 아무것도 하지 않는다.
 * 앱이 꺼진 뒤에도 살아 있도록 분리(detached)해서 실행한다.
 * @returns {boolean} 새로 띄웠는지
 */
export function launchWatchIfNeeded() {
  if (!serviceEnabled() || !printerInstalled() || watcherRunning()) return false;
  const { exe, prefixArgs } = launcher();
  const args = [watchScriptPath(), '--exe', exe, ...prefixArgs.flatMap((arg) => ['--app-arg', arg])];
  try {
    const child = spawn(process.execPath, args, {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      env: { ...cleanEnv(), ELECTRON_RUN_AS_NODE: '1' },
    });
    child.on('error', (error) => log('watcher spawn failed:', error?.message ?? error));
    child.unref();
    log('watcher launched');
    return true;
  } catch (error) {
    log('watcher spawn failed:', error?.message ?? error);
    return false;
  }
}

/** 프린터를 제거할 때: 돌고 있는 감시자를 끈다. 락이 신선한(=살아 있는) 경우에만 종료한다. */
export function stopWatcher() {
  const pid = watcherPid();
  if (!pid) return false;
  try {
    process.kill(pid);
    return true;
  } catch {
    return false;
  }
}

/* -------------------------------------------------------------------------- */
/* printer install / uninstall                                                */
/* -------------------------------------------------------------------------- */

function powershellExe() {
  const root = process.env.SystemRoot || process.env.WINDIR || 'C:\\Windows';
  return path.join(root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
}

function runPowerShell(script) {
  return new Promise((resolve) => {
    const encoded = Buffer.from(script, 'utf16le').toString('base64');
    const child = spawn(
      powershellExe(),
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded],
      { windowsHide: true },
    );
    let output = '';
    child.stdout.on('data', (chunk) => (output += chunk));
    child.stderr.on('data', (chunk) => (output += chunk));
    const timer = setTimeout(() => child.kill(), 90_000);
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ code: 1, output: error.message });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code: code ?? 1, output: output.trim() });
    });
  });
}

function psQuote(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

/** 프린터 「Tiny PDF Editor」(Microsoft Print To PDF 드라이버, 스풀 파일 포트)를 설치한다. */
export async function installPrinter() {
  if (!isWindows) throw new Error('가상 프린터는 Windows에서만 사용할 수 있습니다.');
  const port = spoolFile();
  fs.mkdirSync(spoolDir(), { recursive: true });
  const script = `
$ErrorActionPreference = 'Stop'
$name = ${psQuote(PRINTER_NAME)}
$driver = ${psQuote(PRINTER_DRIVER)}
$port = ${psQuote(port)}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $port) | Out-Null
$existing = Get-Printer -Name $name -ErrorAction SilentlyContinue
if ($existing) { Remove-Printer -Name $name }
$portObj = Get-PrinterPort -Name $port -ErrorAction SilentlyContinue
if (-not $portObj) { Add-PrinterPort -Name $port }
Add-Printer -Name $name -DriverName $driver -PortName $port
`;
  const { code, output } = await runPowerShell(script);
  if (code !== 0) {
    throw new Error(
      '가상 프린터를 설치하지 못했습니다.\n이 PC에 「Microsoft Print to PDF」 드라이버가 있어야 합니다.\n\n' +
        (output || 'PowerShell 오류'),
    );
  }
}

export async function uninstallPrinter() {
  if (!isWindows) return;
  const script = `
$ErrorActionPreference = 'Continue'
$name = ${psQuote(PRINTER_NAME)}
$port = ${psQuote(spoolFile())}
$existing = Get-Printer -Name $name -ErrorAction SilentlyContinue
if ($existing) { Remove-Printer -Name $name }
$portObj = Get-PrinterPort -Name $port -ErrorAction SilentlyContinue
if ($portObj) { Remove-PrinterPort -Name $port -ErrorAction SilentlyContinue }
`;
  await runPowerShell(script);
}

/** 설정 > 가상 프린터 > 설치. */
export async function enablePrinter() {
  await installPrinter();
  writePrinterPref(true);
  if (serviceEnabled()) {
    setWatchAtLogon(true);
    launchWatchIfNeeded();
  }
}

/** 설정 > 가상 프린터 > 제거. */
export async function disablePrinter() {
  await uninstallPrinter();
  writePrinterPref(false);
  setWatchAtLogon(false);
  stopWatcher();
}

/* -------------------------------------------------------------------------- */
/* app lifecycle                                                              */
/* -------------------------------------------------------------------------- */

/**
 * 앱이 시작될 때마다 부른다 (원본 `_ensure_virtual_printer` 와 같은 순서).
 *   · 사용자가 껐으면(false) 아무것도 하지 않는다.
 *   · 켜져 있으면(true) Run 키를 복구하고 감시자가 없으면 띄운다.
 *   · 처음이면(null) 프린터를 설치(이미 있으면 그대로 채택)하고 위와 같이 한다.
 */
export async function ensurePrintService() {
  if (!serviceEnabled()) return;
  const pref = readPrinterPref();
  if (pref === false) return;
  if (pref === true) {
    setWatchAtLogon(true);
    launchWatchIfNeeded();
    return;
  }
  if (process.env.TINY_PRINT_NO_AUTOINSTALL === '1') return;
  try {
    if (!printerInstalled()) await installPrinter();
  } catch (error) {
    log('printer install failed:', error?.message ?? error);
    writePrinterPref(false);
    return;
  }
  writePrinterPref(true);
  setWatchAtLogon(true);
  launchWatchIfNeeded();
}

/**
 * 앱을 끈 직후에도 인쇄가 열리도록 감시자를 이어 준다. 감시자는 원래 앱과 별개로 살아 있으므로
 * 보통은 이미 떠 있어 아무 일도 하지 않지만, 죽어 있었다면 여기서 되살린다.
 */
export function keepWatchAfterQuit() {
  if (!serviceEnabled() || readPrinterPref() !== true) return;
  launchWatchIfNeeded();
}

/**
 * `<앱> --print-watch` (로그인 Run 키)로 시작된 프로세스의 일.
 * 무거운 Electron 을 그대로 두지 않고, 가벼운 Node 감시자를 띄운 뒤 곧바로 끝난다.
 * 감시자를 못 띄우면 호출한 쪽이 이 프로세스에서 직접 감시하도록 false 를 돌려준다.
 */
export function handOffToLightWatcher() {
  if (!printerInstalled()) return true;
  if (watcherRunning()) return true;
  const { exe, prefixArgs } = launcher();
  const args = [watchScriptPath(), '--exe', exe, ...prefixArgs.flatMap((arg) => ['--app-arg', arg])];
  try {
    const child = spawn(process.execPath, args, {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      env: { ...cleanEnv(), ELECTRON_RUN_AS_NODE: '1' },
    });
    child.unref();
    return Boolean(child.pid);
  } catch {
    return false;
  }
}

/** 가벼운 감시자를 못 띄웠을 때의 대안: 이 Electron 프로세스가 직접 스풀을 감시한다. */
export function watchInProcess() {
  const { exe, prefixArgs } = launcher();
  const watcher = startSpoolWatcher({
    onPdf: (pdfPath) => launchEditor({ exe, prefixArgs, pdfPath }),
    onLockLost: () => app.exit(0),
    log,
  });
  if (!watcher) {
    app.exit(0);
    return;
  }
  app.on('will-quit', () => watcher.stop());
}

/* -------------------------------------------------------------------------- */
/* external paths (argv / second-instance)                                    */
/* -------------------------------------------------------------------------- */

/**
 * 명령줄에서 열 후보 경로만 골라낸다. 플래그·실행 파일·앱 폴더는 건너뛴다.
 * 파일이 아직 없어도(브라우저가 첨부를 쓰는 중) 후보는 남긴다.
 * @param {string[]} argv
 * @param {string} [cwd]
 * @returns {string[]}
 */
function candidatePathsFromArgv(argv, cwd = process.cwd()) {
  const skip = new Set([path.resolve(process.execPath).toLowerCase()]);
  if (!app.isPackaged) skip.add(path.resolve(app.getAppPath()).toLowerCase());
  const result = [];
  const seen = new Set();
  for (const raw of argv.slice(1)) {
    const arg = String(raw ?? '').trim();
    if (!arg || arg.startsWith('--') || (arg.startsWith('-') && arg.length <= 3)) continue;
    const full = path.resolve(cwd, arg);
    const key = full.toLowerCase();
    if (skip.has(key) || seen.has(key)) continue;
    seen.add(key);
    result.push(full);
  }
  return result;
}

/**
 * 명령줄에서 지금 존재하는 파일 경로만 골라낸다.
 * @param {string[]} argv
 * @param {string} [cwd]
 * @returns {string[]}
 */
export function pathsFromArgv(argv, cwd = process.cwd()) {
  const result = [];
  for (const full of candidatePathsFromArgv(argv, cwd)) {
    try {
      if (fs.statSync(full).isFile()) result.push(full);
    } catch {
      // 존재하지 않는 인자는 파일이 아니다.
    }
  }
  return result;
}

/**
 * 웹 첨부·다운로드처럼 실행 직후에야 파일이 생기는 경우를 위해 짧게 기다린다.
 * @param {string[]} argv
 * @param {string} [cwd]
 * @param {{ waitMs?: number, stepMs?: number }} [options]
 * @returns {Promise<string[]>}
 */
export async function resolveExternalPaths(argv, cwd = process.cwd(), options = {}) {
  const waitMs = Math.max(0, Number(options.waitMs) || 2000);
  const stepMs = Math.max(50, Number(options.stepMs) || 100);
  const existing = pathsFromArgv(argv, cwd);
  if (existing.length) return existing;

  const candidates = candidatePathsFromArgv(argv, cwd);
  if (!candidates.length || waitMs <= 0) return [];

  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, stepMs));
    const found = [];
    for (const full of candidates) {
      try {
        if (fs.statSync(full).isFile()) found.push(full);
      } catch {
        // 아직 없음
      }
    }
    if (found.length) return found;
  }
  return [];
}
