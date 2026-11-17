/**
 * Update-check helpers (GitHub Releases). Pure functions shared by the main
 * process (fetch) and the renderer (dialog text).
 *
 * @typedef {{
 *   ok: boolean,
 *   configured?: boolean,
 *   current: string,
 *   currentBuildStamp?: string,
 *   latest?: string,
 *   latestBuildStamp?: string | null,
 *   releaseUpdatedAt?: string | null,
 *   releaseUrl?: string,
 *   platformAssetsFound?: boolean,
 *   error?: string,
 * }} UpdateCheckResult
 */

/**
 * 산출물 이름 (scripts/build-common.mjs 의 artifactBase 와 같이 바꾼다):
 *   현재  TinyPDFEditor-NEO-v1.0.0.3-261117_104722_x64.msi
 *         TinyPDFEditor-NEO-v1.0.0.3-portable-261117_104722_x64.zip
 *         TinyPDFEditor-NEO-v1.0.0.3-mac-261117_104722_arm64.zip
 *   예전  TinyPDFEditor-NEO_261117_104722_x64.msi / TinyPDFEditor-NEO_portable_… / TinyPDFEditor-NEO_mac_…
 * 구분자는 `-` 와 `_` 둘 다 받아서 이미 올라간 예전 릴리스도 읽는다.
 */
const BUILD_STAMP_IN_NAME = /[_-](\d{6}_\d{6})(?=[_.])/;
const PORTABLE_ZIP_MARK = /[_-]portable[_-]/;
const MAC_ZIP_MARK = /[_-]mac[_-]/;

/** @param {string} name 산출물 파일 이름에서 빌드 스탬프(YYMMDD_HHMMSS)를 꺼낸다. */
export function buildStampOfName(name) {
  return BUILD_STAMP_IN_NAME.exec(String(name ?? ''))?.[1] ?? null;
}

/** @param {string} name Windows 용 산출물인가 (.msi 또는 포터블 zip). */
export function isWindowsAsset(name) {
  const lower = String(name ?? '').toLowerCase();
  return lower.endsWith('.msi') || (lower.endsWith('.zip') && PORTABLE_ZIP_MARK.test(lower));
}

/** @param {string} name macOS 용 산출물인가 (.dmg 또는 mac zip). */
export function isMacAsset(name) {
  const lower = String(name ?? '').toLowerCase();
  return lower.endsWith('.dmg') || (lower.endsWith('.zip') && MAC_ZIP_MARK.test(lower));
}

/**
 * 릴리스 태그 → 앱 표시 버전. 태그는 `v1.0.0-1`(하이픈), 앱 버전은 `1.0.0.1`(점)이다.
 *   v1.0.0-1 → 1.0.0.1,  v1.0.0.1 → 1.0.0.1,  v1.2 → 1.2
 * 하이픈 뒤 번호를 버리면 `v1.0.0-2` 도 `1.0.0` 이 되어 새 버전을 영영 찾지 못한다.
 * @param {string} tag
 */
export function parseReleaseTag(tag) {
  const text = String(tag ?? '').trim();
  const hyphen = /^v?(\d+\.\d+\.\d+)-(\d+)$/.exec(text);
  if (hyphen) return `${hyphen[1]}.${hyphen[2]}`;
  const match = /^v?(\d+(?:\.\d+){0,3})/.exec(text);
  return match ? match[1] : null;
}

/** @param {string} version */
export function versionTuple(version) {
  return String(version)
    .replace(/^v/, '')
    .split('.')
    .map((part) => Number.parseInt(part, 10) || 0);
}

/**
 * @param {number[]} a
 * @param {number[]} b
 */
export function compareVersionTuples(a, b) {
  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i += 1) {
    const left = a[i] ?? 0;
    const right = b[i] ?? 0;
    if (left > right) return 1;
    if (left < right) return -1;
  }
  return 0;
}

/** @returns {'win' | 'mac' | 'other'} */
export function detectUpdatePlatform(platform = globalThis.process?.platform) {
  if (platform === 'win32') return 'win';
  if (platform === 'darwin') return 'mac';
  return 'other';
}

/**
 * Keeps the release assets that belong to this platform.
 *   Windows: `.msi` and `…-portable-…zip`
 *   macOS:   `.dmg` and `…-mac-…zip`
 * 한 릴리스에 두 플랫폼의 zip 이 함께 올라가므로, zip 은 이름으로 플랫폼을 구분한다.
 *
 * @param {string[]} names
 * @param {'win' | 'mac' | 'other'} [platform]
 */
export function filterAssetsForPlatform(names, platform = detectUpdatePlatform()) {
  return names.filter((name) => {
    if (platform === 'mac') return isMacAsset(name);
    if (platform === 'win') return isWindowsAsset(name);
    return false;
  });
}

/** @param {string[]} names */
export function maxBuildStamp(names) {
  let best = /** @type {string | null} */ (null);
  for (const name of names) {
    const stamp = buildStampOfName(name);
    if (stamp && (!best || stamp > best)) best = stamp;
  }
  return best;
}

/** YYMMDD_HHMMSS → epoch ms (assume 20xx). */
export function buildStampToMs(stamp) {
  const match = /^(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(String(stamp).trim());
  if (!match) return null;
  const ms = Date.UTC(2000 + Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]), Number(match[6]));
  return Number.isFinite(ms) ? ms : null;
}

/**
 * @param {UpdateCheckResult} result
 * @returns {'version' | 'build' | null}
 */
export function resolveUpdateKind(result) {
  if (!result.ok || !result.latest) return null;
  const cmp = compareVersionTuples(versionTuple(result.latest), versionTuple(result.current));
  if (cmp > 0) return 'version';
  if (cmp < 0) return null;

  // Same tag: only compare build stamps when this platform has packages.
  if (result.platformAssetsFound === false) return null;
  const local = String(result.currentBuildStamp || '').trim();
  const remote = String(result.latestBuildStamp || '').trim();
  if (local && remote && remote > local) return 'build';
  return null;
}

/** @param {UpdateCheckResult} result */
export function isUpdateAvailable(result) {
  return resolveUpdateKind(result) != null;
}

/** @param {string} version */
export function versionLabel(version) {
  return String(version).startsWith('v') ? String(version) : `v${version}`;
}
