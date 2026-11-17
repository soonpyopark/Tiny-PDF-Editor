#!/usr/bin/env node
/**
 * npm run build:release  (Windows)
 *
 * One build, one stamp, two artifacts in release/:
 *   TinyPDFEditor-NEO-v<버전>-<YYMMDD_HHMMSS>_<arch>.msi            per-user installer
 *   TinyPDFEditor-NEO-v<버전>-portable-<YYMMDD_HHMMSS>_<arch>.zip   unzip-and-run (data beside the exe)
 *
 * The PDF engine (Python) is frozen first (scripts/build-engine.mjs) and shipped in resources/engine.
 *
 * Needs WiX CLI 4+ (winget install WiXToolset.WiXCLI; wix extension add -g WixToolset.UI.wixext).
 */
import { randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { APP_ID } from '../shared/constants.js';
import { buildEngine } from './build-engine.mjs';
import {
  APP_FILE_NAME,
  APP_NAME,
  APP_VERSION,
  RELEASE_DIR,
  STAGING_DIR,
  artifactBase,
  beginBuild,
  buildRenderer,
  ensureDir,
  findUnpacked,
  packageElectron,
  projectRoot,
} from './build-common.mjs';

const log = (message) => console.log(`[release] ${message}`);

/** electron-builder 가 만든 메인 exe 이름 (package.json build.productName). */
const PRODUCT_NAME = JSON.parse(fs.readFileSync(path.join(projectRoot, 'package.json'), 'utf8')).build.productName;

function findMainExe(dir) {
  const names = fs.readdirSync(dir);
  return (
    names.find((name) => name === `${PRODUCT_NAME}.exe`) ??
    names.find((name) => name.toLowerCase().endsWith('.exe') && !/uninstall|crashpad/i.test(name))
  );
}

function resolveWix() {
  const probe = (command) => spawnSync(command, ['--version'], { encoding: 'utf8' }).status === 0;
  if (probe('wix')) return 'wix';

  const programFiles = process.env.ProgramFiles ?? 'C:\\Program Files';
  for (const version of ['7.0', '6.0', '5.0', '4.0']) {
    const candidate = path.join(programFiles, `WiX Toolset v${version}`, 'bin', 'wix.exe');
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error(
    'WiX CLI not found. Install it with:\n  winget install WiXToolset.WiXCLI\n  wix extension add -g WixToolset.UI.wixext',
  );
}

/**
 * MSI ProductVersion = 앱 버전 그대로 (예: 1.0.0.1) — 프로그램 추가/제거에도 같은 버전이 보인다.
 * 빌드마다 ProductCode 가 새로 만들어지고 Product.wxs 의 MajorUpgrade 가
 * AllowSameVersionUpgrades 이므로, 같은 버전을 다시 빌드해 설치해도 이전 빌드를 교체한다.
 * (Windows Installer 는 업그레이드 비교에서 4번째 자리를 무시한다.)
 */
function toMsiVersion(version) {
  const parts = String(version).split('.').map((part) => Number.parseInt(part, 10) || 0);
  while (parts.length < 4) parts.push(0);
  return parts.slice(0, 4).join('.');
}

/** Zips `<parent>/<folder>` into `zipPath` (bsdtar ships with Windows 10+). */
function zipFolder(parent, folder, zipPath) {
  fs.rmSync(zipPath, { force: true });
  const result = spawnSync('tar', ['-a', '-c', '-f', zipPath, '-C', parent, folder], { stdio: 'inherit' });
  if (result.status !== 0) throw new Error('zip failed (tar exit ' + result.status + ')');
}

function buildPortableZip(unpackedDir, stamp, arch) {
  const folder = artifactBase('portable', stamp, arch);
  const stage = path.join(STAGING_DIR, 'portable');
  const target = path.join(stage, folder);
  fs.rmSync(stage, { recursive: true, force: true });
  fs.cpSync(unpackedDir, target, { recursive: true });

  // The marker makes the app keep its data in ./data beside the exe.
  fs.writeFileSync(path.join(target, '.portable'), '1\n');
  fs.writeFileSync(
    path.join(target, 'README-USB.txt'),
    [
      `${APP_NAME} (portable)`,
      '='.repeat(24),
      '',
      `1. 이 폴더 전체를 원하는 위치(USB 등)에 복사합니다.`,
      `2. ${PRODUCT_NAME}.exe 를 실행합니다.`,
      `3. 설정·회원·백업은 이 폴더의 data/ 에 저장됩니다. (폴더를 통째로 옮기면 그대로 따라갑니다)`,
      `4. 기본 로그인: admin / admin1234  (최초 로그인 후 변경하세요)`,
      `5. LAN 접속은 환경설정 → 서버 관리 에서 허용합니다. (Windows 방화벽 허용이 필요할 수 있음)`,
      '',
      `버전 v${APP_VERSION} / 빌드 ${stamp}_${arch}`,
      '',
    ].join('\r\n'),
  );

  const zipPath = path.join(RELEASE_DIR, `${folder}.zip`);
  zipFolder(stage, folder, zipPath);
  fs.rmSync(stage, { recursive: true, force: true });
  return zipPath;
}

/** Embed icon + ProductName into the packaged exe (taskbar / Explorer). */
async function stampWindowsExe(unpackedDir) {
  const icoPath = path.join(projectRoot, 'build', 'icon.ico');
  if (!fs.existsSync(icoPath)) {
    log('stampWindowsExe: build/icon.ico missing — skipped');
    return;
  }
  const exeName = findMainExe(unpackedDir);
  if (!exeName) {
    log('stampWindowsExe: main exe not found — skipped');
    return;
  }
  const { rcedit } = await import('rcedit');
  // 고정 파일 버전도 앱 버전으로 찍는다. (문자열만 바꾸면 모든 빌드의 exe 가 1.0.0.0 으로 같아져서,
  // 파일 버전을 비교하는 설치/탐색기/진단 도구가 새 빌드를 구분하지 못한다.)
  const exeVersion = toMsiVersion(APP_VERSION);
  await rcedit(path.join(unpackedDir, exeName), {
    icon: icoPath,
    'file-version': exeVersion,
    'product-version': exeVersion,
    'version-string': {
      ProductName: APP_NAME,
      FileDescription: APP_NAME,
      CompanyName: APP_NAME,
      InternalName: APP_FILE_NAME,
      OriginalFilename: exeName,
    },
  });
  log(`stampWindowsExe: icon + version → ${exeName}`);
}

function buildMsi(unpackedDir, stamp, arch) {
  const wix = resolveWix();
  const stage = path.join(STAGING_DIR, 'msi-stage');
  fs.rmSync(stage, { recursive: true, force: true });
  fs.cpSync(unpackedDir, stage, { recursive: true });
  fs.copyFileSync(path.join(projectRoot, 'build', 'icon.ico'), path.join(stage, 'app-icon.ico'));

  const exeName = findMainExe(stage);
  if (!exeName) throw new Error(`Main executable not found in ${stage}`);

  const outPath = path.join(RELEASE_DIR, `${artifactBase('msi', stamp, arch)}.msi`);
  fs.rmSync(outPath, { force: true });

  const productVersion = toMsiVersion(APP_VERSION);
  const args = [
    'build',
    path.join(projectRoot, 'installer', 'Product.wxs'),
    '-d', `AppName=${APP_NAME}`,
    '-d', `AppId=${APP_ID}`,
    '-d', `ExeName=${exeName}`,
    '-d', `ProductVersion=${productVersion}`,
    '-d', `ProductCode=${randomUUID().toUpperCase()}`,
    '-d', `StageDir=${stage}`,
    '-d', `InstallerDir=${path.join(projectRoot, 'installer')}`,
    '-ext', 'WixToolset.UI.wixext',
    '-ext', 'WixToolset.Util.wixext',
    '-o', outPath,
  ];
  log(`> wix ${args.join(' ')}`);
  const result = spawnSync(wix, args, { stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`wix build failed (exit ${result.status})`);

  fs.rmSync(outPath.replace(/\.msi$/i, '.wixpdb'), { force: true });
  fs.rmSync(stage, { recursive: true, force: true });
  return outPath;
}

async function main() {
  if (process.platform !== 'win32') {
    throw new Error('build:release must run on Windows. (macOS: npm run build:release:mac)');
  }

  const arch = process.arch === 'arm64' ? 'arm64' : 'x64';
  const stamp = beginBuild();
  log(`build v${APP_VERSION}, stamp ${stamp}, arch ${arch}`);

  ensureDir(RELEASE_DIR);
  buildRenderer();
  // 사용자 PC 에 Python 이 없어도 되도록 엔진을 동결해 resources/engine 으로 싣는다.
  buildEngine();

  const unpackedRoot = path.join(STAGING_DIR, 'release');
  packageElectron('win', arch, unpackedRoot);
  const unpackedDir = findUnpacked(unpackedRoot, /^win(-arm64)?-unpacked$/);
  await stampWindowsExe(unpackedDir);

  const zipPath = buildPortableZip(unpackedDir, stamp, arch);
  const msiPath = buildMsi(unpackedDir, stamp, arch);
  fs.rmSync(STAGING_DIR, { recursive: true, force: true });

  const size = (file) => `${(fs.statSync(file).size / 1024 / 1024).toFixed(1)} MB`;
  log('done');
  log(`  ${path.relative(projectRoot, msiPath)}  (${size(msiPath)})`);
  log(`  ${path.relative(projectRoot, zipPath)}  (${size(zipPath)})`);
}

main().catch((error) => {
  console.error('[release] failed:', error instanceof Error ? error.message : error);
  process.exit(1);
});
