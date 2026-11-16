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
 * 앱 표시 버전 (점 구분 4단, 예: `1.0.0.0`). All In One Tools 와 같은 표기 규칙.
 * Git 태그는 `v1.0.0-0`(하이픈), package.json 은 `1.0.0-0` 형식을 쓴다.
 */
export const APP_VERSION = '1.0.0.0';

/**
 * Package build id (YYMMDD_HHMMSS). Rewritten by `npm run build:release*`
 * (scripts/sync-build-stamp.mjs); matches the suffix of the produced files.
 */
export const APP_BUILD_STAMP = '261117_004927';

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
 * 업데이트 확인 button. Leave empty until the project has a release page.
 */
export const UPDATE_REPO = '';

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
