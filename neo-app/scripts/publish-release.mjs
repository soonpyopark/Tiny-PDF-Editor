#!/usr/bin/env node
/**
 * npm run publish:release -- --notes-file=<노트.md>   ("배포해줘" 의 마지막 단계)
 *
 * 버전·빌드는 끝나 있어야 한다 (순서는 .cursor/rules/deploy.mdc):
 *   npm run version:bump → npm run build:release(:mac) → 커밋 → 이 스크립트
 *
 * 하는 일:
 *   1. 점검: package.json 버전 = APP_VERSION, main 브랜치, 작업 트리 깨끗함, 이 플랫폼의 산출물 존재
 *   2. 태그 `v1.0.0-N`(APP_GIT_TAG) 생성 → main 과 태그를 GitHub 로 push
 *   3. GitHub Release(제목 `v1.0.0.N`)를 만들고 산출물을 올림
 *        Windows: .msi + 포터블 .zip      macOS: .dmg + _mac_ .zip
 *      릴리스가 이미 있으면(예: Windows 가 먼저 올린 뒤 macOS) 파일만 추가로 올린다.
 *   4. 업로드를 확인한 뒤에만 **이전 릴리스와 이전 태그를 모두 삭제** (원격 + 로컬)
 *        삭제한 태그와 커밋 SHA 는 .cache/logs/publish-release.log 에 남는다 (복구용).
 *
 * 옵션: --notes="…" | --notes-file=경로   (릴리스를 새로 만들 때 필요)
 *       --dry-run          아무것도 바꾸지 않고 할 일만 출력
 *       --keep-previous    이전 릴리스·태그를 지우지 않음
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { APP_BUILD_STAMP, APP_GIT_TAG, APP_NAME, APP_VERSION, UPDATE_REPO } from '../shared/constants.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const repoRoot = path.resolve(root, '..');
const releaseDir = path.join(root, 'release');
const logFile = path.join(root, '.cache', 'logs', 'publish-release.log');

const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const keepPrevious = args.includes('--keep-previous');
const argValue = (name) => args.find((item) => item.startsWith(`${name}=`))?.slice(name.length + 1);

/** 버전 태그로 보이는 것만 정리 대상으로 삼는다 (v1.0.0-1, v1.0.0.1 …). 브랜치·다른 태그는 건드리지 않는다. */
const VERSION_TAG = /^v\d+\.\d+\.\d+([-.]\d+)?$/;

const log = (message) => console.log(`[publish] ${message}`);
const fail = (message) => {
  throw new Error(message);
};

function appendLog(line) {
  fs.mkdirSync(path.dirname(logFile), { recursive: true });
  fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${line}\n`, 'utf8');
}

/**
 * @param {string} command
 * @param {string[]} commandArgs
 * @param {{ cwd?: string, mutating?: boolean, allowFail?: boolean }} [options]
 */
function run(command, commandArgs, { cwd = repoRoot, mutating = false, allowFail = false } = {}) {
  if (mutating && dryRun) {
    log(`(dry-run) ${command} ${commandArgs.join(' ')}`);
    return { status: 0, stdout: '', stderr: '' };
  }
  const result = spawnSync(command, commandArgs, { cwd, encoding: 'utf8' });
  if (result.status !== 0 && !allowFail) {
    fail(`${command} ${commandArgs.join(' ')} 실패 (exit ${result.status})\n${result.stderr || result.stdout}`);
  }
  return result;
}

const git = (gitArgs, options) => run('git', gitArgs, options);
const gh = (ghArgs, options) => run('gh', ghArgs, options);

/** @returns {string[]} */
function lines(text) {
  return String(text ?? '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

/** 이 플랫폼의 산출물 (현재 빌드 스탬프와 같은 것만). */
function findArtifacts() {
  const platform = process.platform;
  if (platform !== 'win32' && platform !== 'darwin') fail('Windows 또는 macOS 에서만 배포할 수 있습니다.');
  if (!fs.existsSync(releaseDir)) fail(`산출물 폴더가 없습니다: ${releaseDir}`);
  const names = fs.readdirSync(releaseDir).filter((name) => name.includes(`_${APP_BUILD_STAMP}_`));
  const wanted = names.filter((name) => {
    const lower = name.toLowerCase();
    if (platform === 'win32') return lower.endsWith('.msi') || (lower.endsWith('.zip') && lower.includes('_portable_'));
    return lower.endsWith('.dmg') || (lower.endsWith('.zip') && lower.includes('_mac_'));
  });
  const need = platform === 'win32' ? ['.msi', '.zip'] : ['.dmg', '.zip'];
  for (const ext of need) {
    if (!wanted.some((name) => name.toLowerCase().endsWith(ext))) {
      fail(`빌드 스탬프 ${APP_BUILD_STAMP} 의 ${ext} 산출물이 없습니다. 먼저 build:release${platform === 'darwin' ? ':mac' : ''} 를 실행하세요.`);
    }
  }
  return wanted.sort().map((name) => path.join(releaseDir, name));
}

function semverOf(version) {
  const m = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(version);
  if (!m) fail(`APP_VERSION 형식이 1.0.0.N 이 아닙니다: ${version}`);
  return `${m[1]}.${m[2]}.${m[3]}-${m[4]}`;
}

function releaseBody(notes, fileNames) {
  return `## 변경\n${notes.trim()}\n\n## 파일\n${fileNames.map((name) => `- ${name}`).join('\n')}\n`;
}

function main() {
  const tag = APP_GIT_TAG;
  const title = `v${APP_VERSION}`;
  const repo = UPDATE_REPO;
  if (!repo) fail('shared/constants.js 의 UPDATE_REPO 가 비어 있습니다.');
  log(`${APP_NAME} ${title} → 태그 ${tag} / 저장소 ${repo}${dryRun ? ' (dry-run)' : ''}`);

  /* ---- 1. 점검 -------------------------------------------------------- */
  if (gh(['auth', 'status'], { allowFail: true }).status !== 0) fail('gh 로그인이 필요합니다: gh auth login');

  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  if (pkg.version !== semverOf(APP_VERSION)) {
    fail(`package.json version(${pkg.version}) 이 APP_VERSION(${APP_VERSION}) 과 다릅니다. npm run version:bump -- --sync`);
  }

  const branch = lines(git(['rev-parse', '--abbrev-ref', 'HEAD']).stdout)[0];
  if (branch !== 'main') fail(`main 브랜치에서만 배포합니다 (현재: ${branch}).`);

  const releaseExists = gh(['release', 'view', tag, '--repo', repo], { allowFail: true }).status === 0;

  // 이미 올라간 릴리스에 파일만 추가하는 경우(macOS 가 두 번째)에는 빌드 스탬프 변경만 허용한다.
  const dirty = lines(git(['status', '--porcelain']).stdout).map((line) => line.slice(3).replace(/\\/g, '/'));
  const allowed = releaseExists ? ['neo-app/shared/constants.js'] : [];
  const blocking = dirty.filter((file) => !allowed.includes(file));
  if (blocking.length > 0) {
    fail(`커밋되지 않은 변경이 있습니다. 먼저 커밋하세요:\n  ${blocking.join('\n  ')}`);
  }

  const artifacts = findArtifacts();
  const fileNames = artifacts.map((file) => path.basename(file));
  log(`산출물: ${fileNames.join(', ')}`);

  /* ---- 2. 태그·push ---------------------------------------------------- */
  if (!releaseExists) {
    const head = lines(git(['rev-parse', 'HEAD']).stdout)[0];
    const existing = git(['rev-parse', '-q', '--verify', `refs/tags/${tag}^{commit}`], { allowFail: true });
    const existingSha = lines(existing.stdout)[0];
    if (existing.status === 0 && existingSha !== head) {
      fail(`로컬 태그 ${tag} 가 현재 커밋이 아닌 ${existingSha?.slice(0, 7)} 를 가리킵니다. 확인 후 지우세요: git tag -d ${tag}`);
    }
    if (existing.status !== 0) git(['tag', '-a', tag, '-m', `${APP_NAME} ${title}`], { mutating: true });
    log(`태그 ${tag} → ${head.slice(0, 7)}`);

    git(['push', 'origin', 'main'], { mutating: true });
    git(['push', 'origin', tag], { mutating: true });
  } else {
    log(`릴리스 ${tag} 가 이미 있어 파일만 추가로 올립니다.`);
  }

  /* ---- 3. 릴리스 -------------------------------------------------------- */
  if (!releaseExists) {
    const notesFile = argValue('--notes-file');
    const notes = argValue('--notes') ?? (notesFile ? fs.readFileSync(path.resolve(notesFile), 'utf8') : '');
    if (!notes.trim()) fail('릴리스를 새로 만들려면 --notes="…" 또는 --notes-file=경로 가 필요합니다.');
    const bodyFile = path.join(root, '.cache', 'release-body.md');
    fs.mkdirSync(path.dirname(bodyFile), { recursive: true });
    fs.writeFileSync(bodyFile, releaseBody(notes, fileNames), 'utf8');
    gh(
      ['release', 'create', tag, ...artifacts, '--repo', repo, '--verify-tag', '--title', title, '--notes-file', bodyFile, '--latest'],
      { mutating: true },
    );
  } else {
    gh(['release', 'upload', tag, ...artifacts, '--repo', repo, '--clobber'], { mutating: true });
    // 본문의 "## 파일" 목록에 새 파일을 이어 붙인다.
    const body = JSON.parse(gh(['release', 'view', tag, '--repo', repo, '--json', 'body']).stdout).body ?? '';
    const missing = fileNames.filter((name) => !body.includes(name));
    if (missing.length > 0) {
      const next = `${body.trimEnd()}\n${missing.map((name) => `- ${name}`).join('\n')}\n`;
      const bodyFile = path.join(root, '.cache', 'release-body.md');
      fs.mkdirSync(path.dirname(bodyFile), { recursive: true });
      fs.writeFileSync(bodyFile, next, 'utf8');
      gh(['release', 'edit', tag, '--repo', repo, '--notes-file', bodyFile], { mutating: true });
    }
  }

  /* ---- 업로드 확인 ------------------------------------------------------ */
  if (!dryRun) {
    const view = JSON.parse(gh(['release', 'view', tag, '--repo', repo, '--json', 'assets,url,isDraft']).stdout);
    const uploaded = new Set(view.assets.filter((asset) => asset.state === 'uploaded').map((asset) => asset.name));
    const absent = fileNames.filter((name) => !uploaded.has(name));
    if (absent.length > 0) fail(`업로드되지 않은 파일이 있어 이전 릴리스를 지우지 않고 중단합니다: ${absent.join(', ')}`);
    if (view.isDraft) fail('릴리스가 초안 상태입니다. 이전 릴리스를 지우지 않고 중단합니다.');
    log(`릴리스 확인 완료: ${view.url}`);
    appendLog(`released ${tag} (${title}) assets=${fileNames.join(',')}`);
  }

  /* ---- 4. 이전 릴리스·태그 삭제 (새 릴리스 확인 뒤에만) ------------------- */
  if (keepPrevious) {
    log('--keep-previous: 이전 릴리스·태그를 지우지 않습니다.');
    return;
  }
  cleanupPrevious(repo, tag);
}

/**
 * 이번 태그 외의 릴리스와 버전 태그를 원격·로컬에서 모두 지운다.
 * @param {string} repo
 * @param {string} keepTag
 */
function cleanupPrevious(repo, keepTag) {
  const releaseTags = JSON.parse(gh(['release', 'list', '--repo', repo, '--limit', '200', '--json', 'tagName']).stdout)
    .map((item) => item.tagName)
    .filter((name) => name !== keepTag);

  const remoteTags = lines(gh(['api', '--paginate', `repos/${repo}/git/matching-refs/tags`, '--jq', '.[].ref']).stdout)
    .map((ref) => ref.replace(/^refs\/tags\//, ''))
    .filter((name) => VERSION_TAG.test(name) && name !== keepTag);

  const localTags = lines(git(['tag', '--list']).stdout).filter((name) => VERSION_TAG.test(name) && name !== keepTag);

  log(`삭제 대상 — 릴리스 ${releaseTags.length}개, 원격 태그 ${remoteTags.length}개, 로컬 태그 ${localTags.length}개`);

  // 복구용: 지우기 전에 태그가 가리키는 커밋을 기록한다.
  const shaOf = (name) => lines(git(['rev-parse', '-q', '--verify', `refs/tags/${name}^{commit}`], { allowFail: true }).stdout)[0] ?? '(로컬에 없음)';
  if (!dryRun) {
    for (const name of new Set([...releaseTags, ...remoteTags, ...localTags])) appendLog(`delete ${name} ${shaOf(name)}`);
  }

  for (const name of releaseTags) {
    gh(['release', 'delete', name, '--repo', repo, '--yes', '--cleanup-tag'], { mutating: true, allowFail: true });
    log(`릴리스 삭제: ${name}`);
  }

  // 릴리스를 지우며 태그도 같이 지워졌을 수 있으므로 남은 원격 태그만 다시 확인한다.
  const stillRemote = dryRun
    ? remoteTags
    : lines(gh(['api', '--paginate', `repos/${repo}/git/matching-refs/tags`, '--jq', '.[].ref']).stdout)
        .map((ref) => ref.replace(/^refs\/tags\//, ''))
        .filter((name) => VERSION_TAG.test(name) && name !== keepTag);
  if (stillRemote.length > 0) {
    git(['push', 'origin', '--delete', ...stillRemote], { mutating: true });
    for (const name of stillRemote) log(`원격 태그 삭제: ${name}`);
  }

  for (const name of localTags) {
    git(['tag', '-d', name], { mutating: true, allowFail: true });
  }
  if (localTags.length > 0) log(`로컬 태그 ${localTags.length}개 삭제`);
  if (!dryRun) log(`삭제 기록(커밋 SHA 포함): ${path.relative(repoRoot, logFile)}`);
}

try {
  main();
} catch (error) {
  console.error('[publish] 실패:', error instanceof Error ? error.message : error);
  process.exit(1);
}
