#!/usr/bin/env node
/**
 * npm run build:release:mac  (macOS only)
 *
 * Produces two artifacts in release/:
 *   TinyPDFEditor-NEO-v<버전>-<YYMMDD_HHMMSS>_<arch>.dmg       disk image (drag to Applications)
 *   TinyPDFEditor-NEO-v<버전>-mac-<YYMMDD_HHMMSS>_<arch>.zip   the .app zipped (same stamp)
 * (arch = this Mac's architecture: arm64 on Apple Silicon, x64 on Intel).
 * `-mac-` in the zip name tells the update check (and humans) it is not the Windows portable zip.
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
  APP_VERSION,
  artifactBase,
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
  log(`build v${APP_VERSION}, stamp ${stamp}, arch ${arch}`);

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

  const dmgPath = path.join(RELEASE_DIR, `${artifactBase('dmg', stamp, arch)}.dmg`);
  fs.rmSync(dmgPath, { force: true });
  tool(
    'hdiutil',
    ['create', '-volname', APP_NAME, '-srcfolder', dmgStage, '-ov', '-format', 'UDZO', dmgPath],
    'hdiutil',
  );

  // zip: ditto -c -k keeps symlinks, permissions and the code signature (zip(1) would break them).
  const zipPath = path.join(RELEASE_DIR, `${artifactBase('mac', stamp, arch)}.zip`);
  fs.rmSync(zipPath, { force: true });
  tool('ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', appPath, zipPath], 'zip');

  fs.rmSync(STAGING_DIR, { recursive: true, force: true });
  const megabytes = (file) => `${(fs.statSync(file).size / 1024 / 1024).toFixed(1)} MB`;
  log('done');
  log(`  ${path.relative(projectRoot, dmgPath)}  (${megabytes(dmgPath)})`);
  log(`  ${path.relative(projectRoot, zipPath)}  (${megabytes(zipPath)})`);
}

try {
  main();
} catch (error) {
  console.error('[release:mac] failed:', error instanceof Error ? error.message : error);
  process.exit(1);
}
