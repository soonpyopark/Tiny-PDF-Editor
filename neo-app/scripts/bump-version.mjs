#!/usr/bin/env node
/**
 * 배포 버전을 한 번에 올린다. (All In One Tools 와 같은 표기 규칙)
 *
 *   npm run version:bump               1.0.0.8 → 1.0.0.9, 1.0.0.9 → 1.0.1.0
 *                                      (끝자리 0–9, 9 다음은 세 번째 자리를 올리고 끝자리는 0)
 *   npm run version:bump -- --set=1.1.0.0
 *   npm run version:bump -- --sync     올리지 않고 package.json·lock 만 APP_VERSION 에 맞춤
 *
 * 바꾸는 곳:
 *   shared/constants.js  APP_VERSION   `1.0.0.N`  (UI·MSI·릴리스 제목은 v1.0.0.N)
 *   package.json         version       `1.0.0-N`
 *   package-lock.json    version       `1.0.0-N`  (루트 항목 두 곳)
 * Git 태그는 `v1.0.0-N` 이며 constants.js 의 APP_GIT_TAG 가 같은 값을 계산한다.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const constantsPath = path.join(root, 'shared', 'constants.js');
const packagePath = path.join(root, 'package.json');
const lockPath = path.join(root, 'package-lock.json');

const VERSION_RE = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/;

function readCurrent() {
  const source = fs.readFileSync(constantsPath, 'utf8');
  const match = /export const APP_VERSION = '([^']*)'/.exec(source);
  if (!match) throw new Error('shared/constants.js 에서 APP_VERSION 을 찾지 못했습니다.');
  if (!VERSION_RE.test(match[1])) throw new Error(`APP_VERSION 형식이 1.0.0.N 이 아닙니다: ${match[1]}`);
  return { source, version: match[1] };
}

/** `1.0.0.1` → `1.0.0-1` */
function semverOf(version) {
  const m = VERSION_RE.exec(version);
  return `${m[1]}.${m[2]}.${m[3]}-${m[4]}`;
}

/** 파일의 들여쓰기·줄바꿈을 유지한 채 JSON 의 최상위 version 을 바꾼다. */
function writeJsonVersion(file, semver, { lock = false } = {}) {
  if (!fs.existsSync(file)) return;
  const text = fs.readFileSync(file, 'utf8');
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const data = JSON.parse(text);
  data.version = semver;
  if (lock && data.packages?.['']) data.packages[''].version = semver;
  fs.writeFileSync(file, `${JSON.stringify(data, null, 2).replace(/\n/g, eol)}${eol}`, 'utf8');
}

const args = process.argv.slice(2);
const { source, version: current } = readCurrent();

let next = current;
const setArg = args.find((item) => item.startsWith('--set='));
if (setArg) {
  next = setArg.slice('--set='.length).replace(/^v/i, '');
  if (!VERSION_RE.test(next)) throw new Error(`--set 값은 1.0.0.N 형식이어야 합니다: ${next}`);
} else if (!args.includes('--sync')) {
  const m = VERSION_RE.exec(current);
  const major = Number(m[1]);
  const minor = Number(m[2]);
  const patch = Number(m[3]);
  const build = Number(m[4]);
  // 끝자리는 한 자리(0–9). 9 다음은 patch+1.0 (1.0.0.9 → 1.0.1.0).
  if (build >= 9) next = `${major}.${minor}.${patch + 1}.0`;
  else next = `${major}.${minor}.${patch}.${build + 1}`;
}

if (next !== current) {
  fs.writeFileSync(
    constantsPath,
    source.replace(/(export const APP_VERSION = )'[^']*'/, `$1'${next}'`),
    'utf8',
  );
}
writeJsonVersion(packagePath, semverOf(next));
writeJsonVersion(lockPath, semverOf(next), { lock: true });

const tag = `v${semverOf(next)}`;
console.log(`[version] ${current} → ${next}  (표시 v${next}, 태그 ${tag}, package.json ${semverOf(next)})`);
