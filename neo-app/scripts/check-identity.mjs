#!/usr/bin/env node
/**
 * Tiny PDF Editor NEO 와 Default Framework 가 서로 섞이지 않는지 검사한다.
 *
 *   npm run check:identity            (build:release / build:release:mac 시작 때도 실행)
 *
 * 두 앱은 같은 템플릿에서 나왔기 때문에, 아래 값이 같으면 실제로 서로를 망가뜨린다.
 *   · MSI UpgradeCode / 컴포넌트 GUID  → 한쪽 설치가 다른 쪽을 "업그레이드"로 덮어씀
 *   · appId · 앱 이름 · 파일 이름         → 사용자 데이터 폴더, 단일 인스턴스 락, 작업표시줄 고정 공유
 *   · 기본 포트                          → dev:stop 이 상대 프로세스를 죽이고, 브라우저 저장소가 섞임
 *
 * 검사 두 가지:
 *   1) 하드코딩한 Default Framework 식별자와 같거나 코드에 남아 있으면 실패
 *   2) Default Framework 폴더가 옆에 있으면(기본: <저장소>/../Default Framework, 또는
 *      DEFAULT_FRAMEWORK_DIR) 실제 값을 읽어 직접 비교
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const NEO = path.resolve(__dirname, '..');

/** 이 앱(Neo)에서는 절대 쓰면 안 되는 Default Framework 의 식별자. */
const DF = {
  appId: 'com.defaultframe.app',
  appFileName: 'DefaultFrame',
  appName: 'Default Framework',
  port: 3001,
  upgradeCode: '7C3E5B9A-2D41-4F6E-8A17-5B0D9E2C4F63',
  componentGuids: ['2B6F1A44-8C3D-4E57-9A02-71D5C8E3B610', '9E0D7C25-4B81-47A9-B3F6-0A52D1C8E974'],
  storageKeys: ['frame.token', 'frame.skippedUpdateNotice'],
  allowlistKind: 'default-frame-ip-allowlist',
};

const problems = [];
const fail = (msg) => problems.push(msg);
const read = (file) => fs.readFileSync(file, 'utf8');

/** `export const NAME = 'x' | 123;` 값을 꺼낸다. */
function constOf(text, name) {
  const m = new RegExp(`export const ${name}\\s*=\\s*(?:'([^']*)'|"([^"]*)"|(\\d+))`).exec(text);
  if (!m) return undefined;
  return m[1] ?? m[2] ?? Number(m[3]);
}

function wxsIds(text) {
  const upgrade = /UpgradeCode="([0-9A-Fa-f-]{36})"/.exec(text)?.[1]?.toUpperCase();
  const guids = [...text.matchAll(/\bGuid="([0-9A-Fa-f-]{36})"/g)].map((m) => m[1].toUpperCase());
  return { upgrade, guids };
}

function sameIgnoreCase(a, b) {
  return a != null && b != null && String(a).toLowerCase() === String(b).toLowerCase();
}

/* ---- Neo 의 현재 값 ---------------------------------------------------- */
const neoConst = read(path.join(NEO, 'shared', 'constants.js'));
const neo = {
  appId: constOf(neoConst, 'APP_ID'),
  appName: constOf(neoConst, 'APP_NAME'),
  appFileName: constOf(neoConst, 'APP_FILE_NAME'),
  port: constOf(neoConst, 'DEFAULT_PORT'),
};
const neoPkg = JSON.parse(read(path.join(NEO, 'package.json')));
const neoWxs = wxsIds(read(path.join(NEO, 'installer', 'Product.wxs')));

for (const [key, value] of Object.entries(neo)) {
  if (value == null || value === '') fail(`shared/constants.js 에서 ${key} 값을 읽지 못했습니다.`);
}
if (neoPkg.build?.appId !== neo.appId) fail(`package.json build.appId(${neoPkg.build?.appId}) 가 APP_ID(${neo.appId}) 와 다릅니다.`);
if (neoPkg.build?.productName !== neo.appName) fail(`package.json build.productName 이 APP_NAME(${neo.appName}) 과 다릅니다.`);
if (!neoWxs.upgrade) fail('installer/Product.wxs 에서 UpgradeCode 를 읽지 못했습니다.');

/* ---- 1) Default Framework 의 알려진 값과 같으면 실패 ---------------------- */
if (sameIgnoreCase(neo.appId, DF.appId)) fail(`APP_ID 가 Default Framework 와 같습니다: ${neo.appId}`);
if (sameIgnoreCase(neo.appName, DF.appName)) fail(`APP_NAME 이 Default Framework 와 같습니다: ${neo.appName}`);
if (sameIgnoreCase(neo.appFileName, DF.appFileName)) fail(`APP_FILE_NAME 이 Default Framework 와 같습니다: ${neo.appFileName}`);
if (neo.port === DF.port) fail(`DEFAULT_PORT 가 Default Framework 와 같습니다: ${neo.port}`);
if (sameIgnoreCase(neoWxs.upgrade, DF.upgradeCode)) {
  fail(`MSI UpgradeCode 가 Default Framework 와 같습니다 (한쪽 설치가 다른 쪽을 덮어씁니다): ${neoWxs.upgrade}`);
}
for (const guid of neoWxs.guids) {
  if (DF.componentGuids.some((g) => sameIgnoreCase(g, guid))) fail(`MSI 컴포넌트 GUID 가 Default Framework 와 같습니다: ${guid}`);
}
if (new Set(neoWxs.guids).size !== neoWxs.guids.length) fail('MSI 컴포넌트 GUID 에 중복이 있습니다.');

/* ---- 코드에 Default Framework 식별자가 남아 있는지 ------------------------- */
// 앱 이름(Default Framework)은 설명 주석에 쓰일 수 있어 텍스트 스캔에서는 뺀다 (APP_NAME 은 위에서 비교).
const FORBIDDEN = [
  DF.appId,
  DF.appFileName,
  DF.allowlistKind,
  ...DF.storageKeys,
  DF.upgradeCode,
  ...DF.componentGuids,
].map((s) => s.toLowerCase());

const SCAN = ['main.js', 'preload.cjs', 'package.json', 'electron', 'shared', 'src', 'installer', 'scripts', 'public', 'index.html'];
const SKIP_DIRS = new Set(['node_modules', 'dist', 'release', '.dist-build', '.engine-build', '.dev-userdata', 'data']);
const SELF = path.join('scripts', 'check-identity.mjs');
const TEXT_EXT = new Set(['.js', '.mjs', '.cjs', '.jsx', '.json', '.wxs', '.html', '.css', '.rtf', '.md', '.txt']);

function* walk(target) {
  const stat = fs.statSync(target, { throwIfNoEntry: false });
  if (!stat) return;
  if (stat.isFile()) {
    yield target;
    return;
  }
  for (const entry of fs.readdirSync(target, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* walk(path.join(target, entry.name));
    } else if (TEXT_EXT.has(path.extname(entry.name).toLowerCase())) {
      yield path.join(target, entry.name);
    }
  }
}

for (const item of SCAN) {
  for (const file of walk(path.join(NEO, item))) {
    const rel = path.relative(NEO, file);
    if (rel === SELF || rel === 'package-lock.json') continue;
    const text = read(file).toLowerCase();
    for (const token of FORBIDDEN) {
      if (text.includes(token)) fail(`${rel} 에 Default Framework 식별자가 남아 있습니다: ${token}`);
    }
  }
}

/* ---- 2) 옆에 있는 Default Framework 의 실제 값과 직접 비교 ------------------ */
const dfDir = process.env.DEFAULT_FRAMEWORK_DIR
  ? path.resolve(process.env.DEFAULT_FRAMEWORK_DIR)
  : path.resolve(NEO, '..', '..', 'Default Framework');
const dfConstFile = path.join(dfDir, 'shared', 'constants.js');
let compared = false;
if (fs.existsSync(dfConstFile)) {
  compared = true;
  const dfConst = read(dfConstFile);
  const live = {
    appId: constOf(dfConst, 'APP_ID'),
    appName: constOf(dfConst, 'APP_NAME'),
    appFileName: constOf(dfConst, 'APP_FILE_NAME'),
    port: constOf(dfConst, 'DEFAULT_PORT'),
  };
  for (const key of Object.keys(live)) {
    if (live[key] != null && sameIgnoreCase(neo[key], live[key])) {
      fail(`${key} 가 옆의 Default Framework(${dfDir}) 와 같습니다: ${neo[key]}`);
    }
  }
  const dfPkgFile = path.join(dfDir, 'package.json');
  if (fs.existsSync(dfPkgFile)) {
    const dfPkg = JSON.parse(read(dfPkgFile));
    if (sameIgnoreCase(dfPkg.name, neoPkg.name)) fail(`package.json name 이 Default Framework 와 같습니다: ${neoPkg.name}`);
    if (sameIgnoreCase(dfPkg.productName ?? dfPkg.build?.productName, neoPkg.build?.productName)) {
      fail('package.json productName 이 Default Framework 와 같습니다.');
    }
  }
  const dfWxsFile = path.join(dfDir, 'installer', 'Product.wxs');
  if (fs.existsSync(dfWxsFile)) {
    const dfWxs = wxsIds(read(dfWxsFile));
    if (sameIgnoreCase(dfWxs.upgrade, neoWxs.upgrade)) fail(`MSI UpgradeCode 가 옆의 Default Framework 와 같습니다: ${neoWxs.upgrade}`);
    for (const guid of neoWxs.guids) {
      if (dfWxs.guids.some((g) => sameIgnoreCase(g, guid))) fail(`MSI 컴포넌트 GUID 가 옆의 Default Framework 와 같습니다: ${guid}`);
    }
  }
}

/* ---- 결과 ----------------------------------------------------------------- */
if (problems.length > 0) {
  console.error('[identity] Tiny PDF Editor NEO 와 Default Framework 의 식별자가 겹칩니다:');
  for (const line of problems) console.error(`  ✗ ${line}`);
  process.exit(1);
}
console.log(
  `[identity] OK — appId=${neo.appId}, port=${neo.port}, UpgradeCode=${neoWxs.upgrade}` +
    (compared ? ` (옆의 Default Framework 와 직접 비교함)` : ' (옆의 Default Framework 폴더가 없어 알려진 값으로만 검사함)'),
);
