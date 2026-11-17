/**
 * App-wide constants shared by the Electron main process, the build scripts
 * and the renderer. Rebrand a new app from this file first.
 */

/** Display name (UI, window title). */
export const APP_NAME = 'Tiny PDF Editor - NEO';

/**
 * Windows Application User Model ID (must match package.json build.appId and
 * the AppUserModelID on Start Menu / Desktop shortcuts). Keeps taskbar pins
 * and their icons stable across reboot and upgrades.
 */
export const APP_ID = 'com.tinypdfeditor.neo';

/** File-system friendly name used in installer / archive file names. */
export const APP_FILE_NAME = 'TinyPDFEditor-NEO';

/**
 * 앱 표시·MSI ProductVersion (점 구분 4단, 예: `1.0.0.1`). All In One Tools 와 같은 표기 규칙.
 *
 * 배포 시 버전 표기 규칙 (이후 릴리스도 동일):
 * - UI / `APP_VERSION` / MSI: `1.0.0.N`  (점)
 * - Git 태그·GitHub Release 태그: `v1.0.0-N`  (하이픈) ← `APP_GIT_TAG`
 * - Release 제목: `v1.0.0.N`
 * - `package.json` version: `1.0.0-N`  (electron-builder semver)
 *
 * N 은 `npm run version:bump` 가 올린다. 직접 고치지 않는다.
 */
export const APP_VERSION = '1.0.0.6';

/**
 * Git 태그 문자열. `1.0.0.1` → `v1.0.0-1`
 * @param {string} [version]
 */
export function formatAppGitTag(version = APP_VERSION) {
  const body = String(version ?? '')
    .trim()
    .replace(/^v/i, '');
  const matched = /^(\d+\.\d+\.\d+)\.(\d+)$/.exec(body);
  if (matched) return `v${matched[1]}-${matched[2]}`;
  return `v${body}`;
}

/** 현재 릴리스용 Git 태그 (예: v1.0.0-1) */
export const APP_GIT_TAG = formatAppGitTag(APP_VERSION);

/**
 * Package build id (YYMMDD_HHMMSS). Rewritten by `npm run build:release*`
 * (scripts/sync-build-stamp.mjs); matches the suffix of the produced files.
 */
export const APP_BUILD_STAMP = '261117_173819';

/**
 * Default web server port (Electron window + LAN browsers share it).
 * Neo's own port: the Default Framework template uses 3001, and `dev:stop` / browser
 * storage are per port, so the two apps must not share a default.
 */
export const DEFAULT_PORT = 3021;

/** Default administrator credentials (seeded on first run). */
export const DEFAULT_ADMIN_ID = 'admin';
export const DEFAULT_ADMIN_PW = 'admin1234';

/**
 * GitHub repository (`owner/repo`) whose latest release is used by the
 * 업데이트 확인 button. Neo 전용 저장소 (Default Framework 와 다르다).
 */
export const UPDATE_REPO = 'soonpyopark/Tiny-PDF-Editor-neo';

/** Content hash of build/icon-source.png (scripts/prepare-icons.mjs). */
export { APP_ICON_REV } from './iconRev.js';

/** Web UI icon (served from public/). Query busts Chrome's sticky favicon cache. */
export const APP_ICON_URL = '/icon.png';

/**
 * @param {string} [stamp]
 * @returns {string} `YYYY-MM-DD HH:MM:SS`
 */
export function formatAppBuildStamp(stamp = APP_BUILD_STAMP) {
  if (/^0+_0+$/.test(String(stamp ?? '').trim())) return '개발 빌드';
  const match = /^(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(String(stamp ?? '').trim());
  if (!match) return String(stamp ?? '').trim();
  return `${2000 + Number(match[1])}-${match[2]}-${match[3]} ${match[4]}:${match[5]}:${match[6]}`;
}
