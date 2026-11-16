import {
  APP_BUILD_STAMP,
  APP_NAME,
  APP_VERSION,
  UPDATE_REPO,
} from '../shared/constants.js';
import {
  detectUpdatePlatform,
  filterAssetsForPlatform,
  maxBuildStamp,
  parseReleaseTag,
} from '../shared/updateCheck.js';

const USER_AGENT = `${APP_NAME.replace(/\s+/g, '')}/${APP_VERSION}`;

/**
 * Latest GitHub release vs. this build. Never throws.
 *
 * @param {number} [timeoutMs]
 * @returns {Promise<import('../shared/updateCheck.js').UpdateCheckResult>}
 */
export async function fetchLatestRelease(timeoutMs = 12_000) {
  const base = { current: APP_VERSION, currentBuildStamp: APP_BUILD_STAMP };

  if (!UPDATE_REPO) {
    return {
      ok: false,
      configured: false,
      ...base,
      error: '업데이트 서버가 설정되지 않았습니다. (shared/constants.js 의 UPDATE_REPO)',
    };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`https://api.github.com/repos/${UPDATE_REPO}/releases/latest`, {
      headers: {
        Accept: 'application/vnd.github+json',
        'User-Agent': USER_AGENT,
        'X-GitHub-Api-Version': '2022-11-28',
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      return { ok: false, configured: true, ...base, error: `GitHub 응답 오류 (HTTP ${response.status})` };
    }

    const payload = await response.json();
    const tagName = String(payload?.tag_name || '');
    const latest = parseReleaseTag(tagName);
    if (!latest) {
      return {
        ok: false,
        configured: true,
        ...base,
        error: `릴리스 버전을 해석할 수 없습니다: ${tagName || '(없음)'}`,
      };
    }

    const assetNames = Array.isArray(payload?.assets)
      ? payload.assets.map((item) => String(item?.name || ''))
      : [];
    const platformNames = filterAssetsForPlatform(assetNames, detectUpdatePlatform());

    return {
      ok: true,
      configured: true,
      ...base,
      latest,
      latestBuildStamp: maxBuildStamp(platformNames),
      releaseUpdatedAt: String(payload?.updated_at || payload?.published_at || '').trim() || null,
      releaseUrl:
        String(payload?.html_url || '').trim() || `https://github.com/${UPDATE_REPO}/releases/latest`,
      platformAssetsFound: platformNames.length > 0,
    };
  } catch (error) {
    const message =
      error instanceof Error && error.name === 'AbortError'
        ? '네트워크 오류 (시간 초과)'
        : error instanceof Error
          ? error.message || '네트워크 오류'
          : '네트워크 오류';
    return { ok: false, configured: true, ...base, error: message };
  } finally {
    clearTimeout(timer);
  }
}
