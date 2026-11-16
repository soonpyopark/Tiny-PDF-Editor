#!/usr/bin/env node
/**
 * npm run dev:stop     — stop the dev app and release everything it holds
 * npm run dev:restart  — stop, then start `npm run dev` again
 *
 * "Everything" = the HTTP port (the dev server, Vite HMR and the API all share
 * one port), every Electron process started from this project (main, GPU,
 * renderer, utility) and stale single-instance lock files.
 */
import { execFileSync, execSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_PORT } from '../shared/constants.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, '..');
const command = process.argv[2] ?? 'restart';
const isWin = process.platform === 'win32';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Same precedence as the app: APP_PORT env > settings.json > .env > default. */
function resolvePort() {
  const fromEnv = Number(process.env.APP_PORT);
  if (Number.isInteger(fromEnv) && fromEnv > 0) return fromEnv;

  try {
    const settings = JSON.parse(fs.readFileSync(path.join(projectRoot, 'data', 'settings.json'), 'utf8'));
    const stored = Number(settings?.webServerPort);
    if (Number.isInteger(stored) && stored > 0) return stored;
  } catch {
    // no settings yet
  }

  try {
    const env = fs.readFileSync(path.join(projectRoot, '.env'), 'utf8');
    const match = /^\s*APP_PORT\s*=\s*(\d+)/m.exec(env);
    if (match) return Number(match[1]);
  } catch {
    // no .env
  }
  return DEFAULT_PORT;
}

/** @param {number} port @returns {number[]} */
function getListeningPids(port) {
  try {
    if (isWin) {
      const output = execSync(`netstat -ano -p tcp`, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      const pids = new Set();
      for (const line of output.split(/\r?\n/)) {
        if (!line.includes('LISTENING')) continue;
        const parts = line.trim().split(/\s+/);
        if (!parts[1]?.endsWith(`:${port}`)) continue;
        const pid = Number(parts.at(-1));
        if (pid > 0) pids.add(pid);
      }
      return [...pids];
    }
    const output = execSync(`lsof -ti tcp:${port} -sTCP:LISTEN`, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    return output.split(/\r?\n/).map((line) => Number(line.trim())).filter((pid) => pid > 0);
  } catch {
    return [];
  }
}

/** Electron processes whose binary / args live under this project. @returns {number[]} */
function getProjectElectronPids() {
  const marker = projectRoot.toLowerCase();
  try {
    if (isWin) {
      const script =
        "Get-CimInstance Win32_Process -Filter \"Name='electron.exe'\" | " +
        'Select-Object ProcessId,CommandLine,ExecutablePath | ConvertTo-Json -Compress';
      const raw = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return (Array.isArray(parsed) ? parsed : [parsed])
        .filter((p) => `${p.CommandLine ?? ''} ${p.ExecutablePath ?? ''}`.toLowerCase().includes(marker))
        .map((p) => Number(p.ProcessId));
    }
    const output = execSync(`pgrep -f "${path.join(projectRoot, 'node_modules', 'electron')}"`, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    return output.split(/\r?\n/).map((line) => Number(line.trim())).filter((pid) => pid > 0);
  } catch {
    return [];
  }
}

/** @param {number} pid */
function killPidTree(pid) {
  if (pid === process.pid) return;
  try {
    if (isWin) execSync(`taskkill /PID ${pid} /T /F`, { stdio: 'ignore' });
    else process.kill(pid, 'SIGKILL');
  } catch {
    // already gone
  }
}

/** @param {number} port */
function isPortFree(port) {
  return new Promise((resolve) => {
    const tester = net.createServer();
    tester.once('error', () => resolve(false));
    tester.once('listening', () => tester.close(() => resolve(true)));
    tester.listen(port, '127.0.0.1');
  });
}

/** @param {number} port */
async function waitForPortFree(port, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (getListeningPids(port).length === 0 && (await isPortFree(port))) return true;
    await sleep(300);
  }
  return false;
}

async function stopDev() {
  const port = resolvePort();
  const electronPids = getProjectElectronPids();
  const portPids = getListeningPids(port);
  const targets = [...new Set([...electronPids, ...portPids])];

  if (targets.length === 0) {
    console.log(`[dev:stop] Nothing is running (port ${port} is free).`);
  } else {
    console.log(`[dev:stop] Stopping PID(s): ${targets.join(', ')} (port ${port})`);
    for (const pid of targets) killPidTree(pid);
  }

  // Wait until no project Electron process is left, then until the port is free.
  const deadline = Date.now() + 10_000;
  while (getProjectElectronPids().length > 0 && Date.now() < deadline) {
    for (const pid of getProjectElectronPids()) killPidTree(pid);
    await sleep(300);
  }

  if (!(await waitForPortFree(port))) {
    console.error(`[dev:stop] Port ${port} is still in use by another program. Close it manually and retry.`);
    process.exit(1);
  }

  // Chromium leaves stale single-instance locks behind on macOS / Linux.
  if (!isWin) {
    for (const name of ['SingletonLock', 'SingletonSocket', 'SingletonCookie']) {
      fs.rmSync(path.join(projectRoot, '.dev-userdata', name), { force: true });
    }
  }

  console.log(`[dev:stop] Done — port ${port} released, no Electron process left.`);
}

async function restartDev() {
  await stopDev();
  console.log('[dev:restart] Starting npm run dev …');
  const child = spawn('npm run dev', {
    cwd: projectRoot,
    stdio: 'inherit',
    shell: true,
    env: process.env,
  });
  child.on('exit', (code) => process.exit(code ?? 0));
}

if (command === 'stop') {
  await stopDev();
} else if (command === 'restart') {
  await restartDev();
} else {
  console.error('Usage: node scripts/dev-process.mjs [stop|restart]');
  process.exit(1);
}
