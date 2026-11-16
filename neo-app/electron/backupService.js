import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import JSZip from 'jszip';
import { APP_FILE_NAME, APP_VERSION } from '../shared/constants.js';
import { getStateRoot, statePath } from './context.js';
import { reloadMembers } from './membersService.js';
import { getSettings, reloadSettings, updateSettings } from './settingsService.js';

const BACKUP_DIR = 'backups';
const MANIFEST_NAME = '_backup.json';
const NAME_PATTERN = /^backup_\d{6}_\d{6}_(manual|auto|prerestore|imported)(-\d+)?\.zip$/;

/** Runtime-only files that must never travel inside a backup. */
const EXCLUDED_FILES = new Set(['sessions.json']);

/**
 * @typedef {'manual' | 'auto' | 'prerestore' | 'imported'} BackupKind
 * @typedef {{ fileName: string, size: number, createdAt: number, kind: BackupKind }} BackupEntry
 */

function backupDir() {
  return statePath(BACKUP_DIR);
}

/** @param {Date} [date] */
function stampOf(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${String(date.getFullYear()).slice(-2)}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(
    date.getHours(),
  )}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

/**
 * 백업 zip 이 이 프로그램(Tiny PDF Editor NEO)이 만든 것인지 manifest 로 확인한다.
 * 같은 템플릿에서 나온 다른 앱(예: Default Framework)의 백업을 가져오거나 복원해
 * 설정·회원 정보를 덮어쓰는 일을 막는다.
 * @param {JSZip} zip
 */
async function assertOwnBackup(zip) {
  const entry = zip.file(MANIFEST_NAME);
  if (!entry) throw new Error('이 프로그램의 백업 파일이 아닙니다.');
  let app = '';
  try {
    app = String(JSON.parse(await entry.async('string'))?.app ?? '');
  } catch {
    // fall through: treated as foreign
  }
  if (app !== APP_FILE_NAME) throw new Error('이 프로그램의 백업 파일이 아닙니다.');
}

/** @param {string} fileName */
function assertBackupName(fileName) {
  const name = String(fileName ?? '');
  if (!NAME_PATTERN.test(name)) throw new Error('올바르지 않은 백업 파일 이름입니다.');
  return name;
}

/** @param {string} baseName without extension */
function uniqueBackupPath(baseName) {
  let candidate = path.join(backupDir(), `${baseName}.zip`);
  for (let i = 2; fs.existsSync(candidate); i += 1) {
    candidate = path.join(backupDir(), `${baseName}-${i}.zip`);
  }
  return candidate;
}

/**
 * Everything under the state root except backups/ and runtime-only files.
 * New features that store files there are backed up automatically.
 *
 * @param {string} dir
 * @param {string} [prefix]
 * @returns {Promise<string[]>} posix-style relative paths
 */
async function collectFiles(dir, prefix = '') {
  /** @type {string[]} */
  const files = [];
  const entries = await fsp.readdir(dir, { withFileTypes: true }).catch(() => []);
  for (const entry of entries) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (!prefix && entry.name === BACKUP_DIR) continue;
    if (!prefix && EXCLUDED_FILES.has(entry.name)) continue;
    if (entry.name.endsWith('.tmp')) continue;
    if (entry.isDirectory()) files.push(...(await collectFiles(path.join(dir, entry.name), rel)));
    else if (entry.isFile()) files.push(rel);
  }
  return files;
}

/** @param {string} fileName @returns {BackupKind} */
function kindOf(fileName) {
  return /** @type {BackupKind} */ (NAME_PATTERN.exec(fileName)?.[1] ?? 'manual');
}

/** @returns {Promise<BackupEntry[]>} newest first */
export async function listBackups() {
  const entries = await fsp.readdir(backupDir(), { withFileTypes: true }).catch(() => []);
  /** @type {BackupEntry[]} */
  const result = [];
  for (const entry of entries) {
    if (!entry.isFile() || !NAME_PATTERN.test(entry.name)) continue;
    const stat = await fsp.stat(path.join(backupDir(), entry.name)).catch(() => null);
    if (!stat) continue;
    result.push({
      fileName: entry.name,
      size: stat.size,
      createdAt: stat.mtimeMs,
      kind: kindOf(entry.name),
    });
  }
  return result.sort((a, b) => b.createdAt - a.createdAt);
}

/** Keeps the newest `keepCount` automatic backups; manual ones are never pruned. */
async function pruneAutoBackups() {
  const { keepCount } = getSettings().backup;
  const autos = (await listBackups()).filter((b) => b.kind === 'auto');
  for (const old of autos.slice(keepCount)) {
    await fsp.rm(path.join(backupDir(), old.fileName), { force: true });
  }
}

/**
 * @param {BackupKind} [kind]
 * @returns {Promise<BackupEntry>}
 */
export async function runBackup(kind = 'manual') {
  const root = getStateRoot();
  const zip = new JSZip();
  const files = await collectFiles(root);
  for (const rel of files) {
    zip.file(rel, await fsp.readFile(path.join(root, rel)));
  }
  zip.file(
    MANIFEST_NAME,
    JSON.stringify({ app: APP_FILE_NAME, version: APP_VERSION, createdAt: Date.now(), files: files.length }, null, 2),
  );

  const buffer = await zip.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
  });

  await fsp.mkdir(backupDir(), { recursive: true });
  const target = uniqueBackupPath(`backup_${stampOf()}_${kind}`);
  await fsp.writeFile(target, buffer);

  if (kind === 'auto') await pruneAutoBackups();
  const stat = await fsp.stat(target);
  return { fileName: path.basename(target), size: stat.size, createdAt: stat.mtimeMs, kind };
}

/** @param {string} fileName */
export async function deleteBackup(fileName) {
  await fsp.rm(path.join(backupDir(), assertBackupName(fileName)), { force: true });
}

/** @param {string} fileName @returns {Promise<Buffer>} */
export async function readBackup(fileName) {
  return fsp.readFile(path.join(backupDir(), assertBackupName(fileName)));
}

/**
 * Stores an uploaded zip after checking it really is one of our backups.
 * @param {Buffer} buffer
 */
export async function importBackup(buffer) {
  const zip = await JSZip.loadAsync(buffer).catch(() => {
    throw new Error('올바른 백업 파일(zip)이 아닙니다.');
  });
  await assertOwnBackup(zip);

  await fsp.mkdir(backupDir(), { recursive: true });
  const target = uniqueBackupPath(`backup_${stampOf()}_imported`);
  await fsp.writeFile(target, buffer);
  const stat = await fsp.stat(target);
  return {
    fileName: path.basename(target),
    size: stat.size,
    createdAt: stat.mtimeMs,
    kind: /** @type {BackupKind} */ ('imported'),
  };
}

/**
 * Overlays a backup onto the state root. A `prerestore` backup of the current
 * state is taken first so a bad restore can itself be undone.
 *
 * @param {string} fileName
 */
export async function restoreBackup(fileName) {
  const source = path.join(backupDir(), assertBackupName(fileName));
  const zip = await JSZip.loadAsync(await fsp.readFile(source));
  await assertOwnBackup(zip);

  await runBackup('prerestore');

  const root = path.resolve(getStateRoot());
  let restored = 0;
  for (const [name, entry] of Object.entries(zip.files)) {
    if (entry.dir || name === MANIFEST_NAME) continue;
    const target = path.resolve(root, name);
    // Zip-slip guard + never let a backup overwrite the backups themselves.
    if (!target.startsWith(root + path.sep)) continue;
    const top = path.relative(root, target).split(path.sep)[0];
    if (top === BACKUP_DIR || EXCLUDED_FILES.has(top)) continue;

    await fsp.mkdir(path.dirname(target), { recursive: true });
    await fsp.writeFile(target, await entry.async('nodebuffer'));
    restored += 1;
  }

  reloadSettings();
  reloadMembers();
  return { restored };
}

/* -------------------------------------------------------------------------- */
/* scheduler                                                                  */
/* -------------------------------------------------------------------------- */

/** @type {ReturnType<typeof setInterval> | null} */
let timer = null;
let running = false;

async function tick() {
  if (running) return;
  const { autoEnabled, intervalHours, lastRunAt } = getSettings().backup;
  if (!autoEnabled) return;
  if (lastRunAt && Date.now() - lastRunAt < intervalHours * 3_600_000) return;

  running = true;
  try {
    await runBackup('auto');
    await updateSettings({ backup: { lastRunAt: Date.now() } });
    console.log('[backup] automatic backup done');
  } catch (err) {
    console.warn('[backup] automatic backup failed:', err);
  } finally {
    running = false;
  }
}

export function startBackupScheduler() {
  if (timer) return;
  timer = setInterval(() => void tick(), 60_000);
  timer.unref?.();
  setTimeout(() => void tick(), 15_000).unref?.();
}

export function stopBackupScheduler() {
  if (timer) clearInterval(timer);
  timer = null;
}
