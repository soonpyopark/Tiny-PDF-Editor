import { api } from './apiClient.js';
import { UPDATE_REPO } from '../../shared/constants.js';
import { isUpdateAvailable, resolveUpdateKind, versionLabel } from '../../shared/updateCheck.js';
import { openExternalUrl } from './openExternal.js';

const SKIPPED_UPDATE_KEY = 'frame.skippedUpdateNotice';

const releasesPage = () => (UPDATE_REPO ? `https://github.com/${UPDATE_REPO}/releases` : '');

/** @param {import('../../shared/updateCheck.js').UpdateCheckResult} result */
function noticeKey(result) {
  return [result.latest || '', result.latestBuildStamp || ''].join('|');
}

/** @param {import('../../shared/updateCheck.js').UpdateCheckResult} result */
function isSkipped(result) {
  try {
    return window.localStorage.getItem(SKIPPED_UPDATE_KEY) === noticeKey(result);
  } catch {
    return false;
  }
}

/** @param {import('../../shared/updateCheck.js').UpdateCheckResult} result */
function skip(result) {
  try {
    window.localStorage.setItem(SKIPPED_UPDATE_KEY, noticeKey(result));
  } catch {
    // ignore
  }
}

/** @param {import('../../shared/updateCheck.js').UpdateCheckResult} result */
function availableBody(result) {
  const current = versionLabel(result.current);
  const latest = versionLabel(result.latest || '');
  const currentHint = result.currentBuildStamp ? `${current} (${result.currentBuildStamp})` : current;
  if (resolveUpdateKind(result) === 'build') {
    const stamp = result.latestBuildStamp ? `\n최신 빌드: ${result.latestBuildStamp}` : '';
    return `같은 버전의 새 빌드가 있습니다: ${latest}\n\n현재 버전: ${currentHint}${stamp}`;
  }
  return `새 버전이 있습니다: ${latest}\n\n현재 버전: ${currentHint}`;
}

/**
 * Manual 업데이트 확인 (top bar button).
 * @param {ReturnType<typeof import('../context/DialogContext.jsx').useDialog>} dialog
 */
export async function runUpdateCheck(dialog) {
  const title = '업데이트 확인';
  let result;
  try {
    result = await api('update.check');
  } catch (err) {
    await dialog.alert({ title, body: err instanceof Error ? err.message : '확인에 실패했습니다.' });
    return;
  }

  if (result.configured === false) {
    await dialog.alert({
      title,
      body: `업데이트 서버가 설정되지 않았습니다.\n\n현재 버전: ${versionLabel(result.current)} (${result.currentBuildStamp})\n\nshared/constants.js 의 UPDATE_REPO 에 GitHub 저장소(owner/repo)를 지정하면 릴리스 기준으로 확인합니다.`,
    });
    return;
  }

  if (!result.ok) {
    const open = await dialog.confirm({
      title,
      body: `업데이트 정보를 확인할 수 없습니다.\n\n${result.error || '알 수 없는 오류'}\n\n현재 버전: ${versionLabel(result.current)}`,
      confirmLabel: '릴리스 페이지 열기',
      cancelLabel: '닫기',
    });
    if (open) await openExternalUrl(releasesPage());
    return;
  }

  if (isUpdateAvailable(result)) {
    const open = await dialog.confirm({
      title,
      body: availableBody(result),
      confirmLabel: '다운로드',
      cancelLabel: '나중에',
    });
    if (open) await openExternalUrl(result.releaseUrl || releasesPage());
    return;
  }

  const current = versionLabel(result.current);
  await dialog.alert({
    title,
    body: `최신 버전입니다.\n\n현재 버전: ${result.currentBuildStamp ? `${current} (${result.currentBuildStamp})` : current}`,
  });
}

/**
 * Quiet check on startup — only prompts when a newer build exists.
 * @param {ReturnType<typeof import('../context/DialogContext.jsx').useDialog>} dialog
 */
export async function runStartupUpdateCheck(dialog) {
  let result;
  try {
    result = await api('update.check');
  } catch {
    return;
  }
  if (!result.ok || !isUpdateAvailable(result) || isSkipped(result)) return;

  const choice = await dialog.choose({
    title: '업데이트',
    body: availableBody(result),
    primaryLabel: '다운로드',
    extraLabel: '이 버전은 알리지 않기',
    cancelLabel: '나중에',
  });
  if (choice === 'primary') await openExternalUrl(result.releaseUrl || releasesPage());
  if (choice === 'extra') skip(result);
}
