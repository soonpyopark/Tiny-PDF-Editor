import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { APP_FILE_NAME, APP_NAME, APP_VERSION } from '../shared/constants.js';
import { formatBuildTimestamp, writeBuildStamp } from './sync-build-stamp.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const projectRoot = path.resolve(__dirname, '..');

/** Final artifacts land here. */
export const RELEASE_DIR = path.join(projectRoot, 'release');

/** electron-builder unpack output (intermediate). */
export const STAGING_DIR = path.join(projectRoot, '.dist-build');

export { APP_FILE_NAME, APP_NAME, APP_VERSION, formatBuildTimestamp };

/**
 * Artifact base name (no extension) — every build output uses it, so version and stamp are always in the name:
 *   msi       TinyPDFEditor-NEO-v1.0.0.3-261117_104722_x64
 *   portable  TinyPDFEditor-NEO-v1.0.0.3-portable-261117_104722_x64   (Windows zip)
 *   dmg       TinyPDFEditor-NEO-v1.0.0.3-261117_104722_arm64
 *   mac       TinyPDFEditor-NEO-v1.0.0.3-mac-261117_104722_arm64      (macOS zip)
 * `portable` / `mac` tell the update check (and humans) which platform a zip belongs to.
 * shared/updateCheck.js parses these names, so change both together.
 * @param {'msi' | 'portable' | 'dmg' | 'mac'} kind
 * @param {string} stamp YYMMDD_HHMMSS
 * @param {string} arch
 */
export function artifactBase(kind, stamp, arch) {
  const marker = kind === 'portable' || kind === 'mac' ? `-${kind}` : '';
  return `${APP_FILE_NAME}-v${APP_VERSION}${marker}-${stamp}_${arch}`;
}

/**
 * Stamps shared/constants.js, so the app reports the same build id that is in
 * the artifact names.
 * @param {string} [stamp]
 */
export function beginBuild(stamp = formatBuildTimestamp()) {
  assertDistinctIdentity();
  writeBuildStamp(stamp);
  return stamp;
}

/**
 * 릴리스를 만들기 전에 Neo 의 식별자(UpgradeCode·appId·포트 등)가 Default Framework 와
 * 겹치지 않는지 확인한다. 겹치면 설치본이 서로를 덮어쓰므로 빌드를 중단한다.
 */
export function assertDistinctIdentity() {
  const result = spawnSync(process.execPath, [path.join(__dirname, 'check-identity.mjs')], { stdio: 'inherit' });
  if (result.status !== 0) {
    throw new Error('식별자 검사 실패: Default Framework 와 겹치는 값을 고친 뒤 다시 빌드하세요.');
  }
}

/**
 * @param {string} command
 * @param {string[]} args
 * @param {import('node:child_process').SpawnSyncOptions} [options]
 */
export function run(command, args, options = {}) {
  console.log(`> ${[command, ...args].join(' ')}`);
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    stdio: 'inherit',
    shell: process.platform === 'win32',
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(`Command failed (exit ${result.status ?? 'null'}): ${command} ${args.join(' ')}`);
  }
}

/** Icons + production renderer bundle (dist/). */
export function buildRenderer() {
  run('npm', ['run', 'build']);
}

/**
 * Packages the Electron app as an unpacked folder / .app.
 * @param {'win' | 'mac'} platform
 * @param {string} arch x64 | arm64
 * @param {string} outputDir
 */
export function packageElectron(platform, arch, outputDir) {
  fs.rmSync(outputDir, { recursive: true, force: true });
  const relative = path.relative(projectRoot, outputDir).split(path.sep).join('/');
  run('npx', [
    'electron-builder',
    `--${platform}`,
    'dir',
    `--${arch}`,
    `-c.directories.output=${relative}`,
  ]);
}

/**
 * @param {string} dir
 * @param {RegExp} pattern
 */
export function findUnpacked(dir, pattern) {
  const matches = fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && pattern.test(entry.name));
  if (matches.length !== 1) {
    throw new Error(
      `Unpacked build not found in ${dir} (found: ${matches.map((m) => m.name).join(', ') || 'none'})`,
    );
  }
  return path.join(dir, matches[0].name);
}

/** @param {string} target */
export function ensureDir(target) {
  fs.mkdirSync(target, { recursive: true });
  return target;
}
