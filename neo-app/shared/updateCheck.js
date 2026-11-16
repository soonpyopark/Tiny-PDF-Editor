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

const BUILD_STAMP_IN_NAME = /_(\d{6}_\d{6})(?=[_.])/;

/** @param {string} tag */
export function parseReleaseTag(tag) {
  const match = /^v?(\d+(?:\.\d+){0,3})/.exec(String(tag ?? '').trim());
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
 * Keeps the release assets that belong to this platform
 * (.msi / _portable...zip on Windows, .dmg on macOS).
 *
 * @param {string[]} names
 * @param {'win' | 'mac' | 'other'} [platform]
 */
export function filterAssetsForPlatform(names, platform = detectUpdatePlatform()) {
  return names.filter((name) => {
    const lower = name.toLowerCase();
    if (platform === 'mac') return lower.endsWith('.dmg');
    if (platform === 'win') return lower.endsWith('.msi') || lower.endsWith('.zip');
    return false;
  });
}

/** @param {string[]} names */
export function maxBuildStamp(names) {
  let best = /** @type {string | null} */ (null);
  for (const name of names) {
    const stamp = BUILD_STAMP_IN_NAME.exec(name)?.[1];
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
