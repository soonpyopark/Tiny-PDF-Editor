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
 * Artifact name suffix: `_YYMMDD_HHMMSS_<arch>` (e.g. `_261029_153000_arm64`).
 * @param {string} stamp
 * @param {string} arch
 */
export function artifactSuffix(stamp, arch) {
  return `_${stamp}_${arch}`;
}

/**
 * Stamps shared/constants.js, so the app reports the same build id that is in
 * the artifact names.
 * @param {string} [stamp]
 */
export function beginBuild(stamp = formatBuildTimestamp()) {
  writeBuildStamp(stamp);
  return stamp;
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
