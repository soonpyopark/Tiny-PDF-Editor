#!/usr/bin/env node
/**
 * npm run build:release:mac  (macOS only)
 *
 * Produces release/TinyPDFEditor-NEO_<YYMMDD_HHMMSS>_<arch>.dmg
 * (arch = this Mac's architecture: arm64 on Apple Silicon, x64 on Intel).
 *
 * The app is ad-hoc signed (`codesign --sign -`): enough to launch on Apple
 * Silicon. It is NOT notarized — for distribution outside your own machines,
 * add a Developer ID certificate (package.json build.mac.identity).
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {
  APP_FILE_NAME,
  APP_NAME,
  RELEASE_DIR,
  STAGING_DIR,
  artifactSuffix,
  beginBuild,
  buildRenderer,
  ensureDir,
  findUnpacked,
  packageElectron,
  projectRoot,
} from './build-common.mjs';

const log = (message) => console.log(`[release:mac] ${message}`);

function tool(command, args, label) {
  const result = spawnSync(command, args, { stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`${label} failed (exit ${result.status ?? 'null'})`);
}

function main() {
  if (process.platform !== 'darwin') {
    throw new Error('build:release:mac must run on macOS (dmg needs hdiutil). On Windows use: npm run build:release');
  }

  const arch = process.arch === 'arm64' ? 'arm64' : 'x64';
  const stamp = beginBuild();
  const suffix = artifactSuffix(stamp, arch);
  log(`build stamp ${stamp}, arch ${arch}`);

  ensureDir(RELEASE_DIR);
  buildRenderer();

  const unpackedRoot = path.join(STAGING_DIR, 'mac');
  packageElectron('mac', arch, unpackedRoot);
  const appPath = path.join(findUnpacked(unpackedRoot, /^mac/), `${APP_FILE_NAME}.app`);
  if (!fs.existsSync(appPath)) throw new Error(`${APP_FILE_NAME}.app not found (${appPath})`);

  tool('codesign', ['--force', '--deep', '--sign', '-', appPath], 'ad-hoc codesign');

  // Installer-style disk image: the app + an Applications shortcut.
  const dmgStage = path.join(STAGING_DIR, 'dmg');
  fs.rmSync(dmgStage, { recursive: true, force: true });
  ensureDir(dmgStage);
  // ditto keeps the framework symlinks intact (fs.cp would rewrite them).
  tool('ditto', [appPath, path.join(dmgStage, `${APP_FILE_NAME}.app`)], 'dmg staging');
  fs.symlinkSync('/Applications', path.join(dmgStage, 'Applications'));

  const dmgPath = path.join(RELEASE_DIR, `${APP_FILE_NAME}${suffix}.dmg`);
  fs.rmSync(dmgPath, { force: true });
  tool(
    'hdiutil',
    ['create', '-volname', APP_NAME, '-srcfolder', dmgStage, '-ov', '-format', 'UDZO', dmgPath],
    'hdiutil',
  );

  fs.rmSync(STAGING_DIR, { recursive: true, force: true });
  const size = `${(fs.statSync(dmgPath).size / 1024 / 1024).toFixed(1)} MB`;
  log('done');
  log(`  ${path.relative(projectRoot, dmgPath)}  (${size})`);
}

try {
  main();
} catch (error) {
  console.error('[release:mac] failed:', error instanceof Error ? error.message : error);
  process.exit(1);
}
