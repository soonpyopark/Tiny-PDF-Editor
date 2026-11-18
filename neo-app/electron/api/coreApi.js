import {
  APP_BUILD_STAMP,
  APP_FILE_NAME,
  APP_NAME,
  APP_VERSION,
  UPDATE_REPO,
  formatAppBuildStamp,
} from '../../shared/constants.js';
import { normalizeAccentColor } from '../../shared/theme.js';
import { runtime } from '../runtime.js';
import { getPublicSettings, getSettings, updateSettings } from '../settingsService.js';
import { fetchLatestRelease } from '../updateService.js';
import { ApiError, defineApi } from './registry.js';

/** `settings.json` + OS-level values the settings UI shows together. */
function settingsPayload() {
  return {
    ...getSettings(),
    autoLaunch: runtime.autoLaunch?.get() ?? false,
    autoLaunchSupported: runtime.autoLaunch?.supported ?? false,
  };
}

export function registerCoreApi() {
  defineApi('app.info', 'public', () => ({
    name: APP_NAME,
    fileName: APP_FILE_NAME,
    version: APP_VERSION,
    buildStamp: APP_BUILD_STAMP,
    buildStampLabel: formatAppBuildStamp(APP_BUILD_STAMP),
    updateConfigured: Boolean(UPDATE_REPO),
    ...getPublicSettings(),
  }));

  defineApi('update.check', 'user', () => fetchLatestRelease());

  defineApi('settings.get', 'admin', () => settingsPayload());

  defineApi('settings.update', 'admin', async (body) => {
    /** @type {Record<string, unknown>} */
    const patch = {};
    if ('accentColor' in body) patch.accentColor = normalizeAccentColor(body.accentColor);
    if ('startupUpdateCheck' in body) patch.startupUpdateCheck = Boolean(body.startupUpdateCheck);
    if ('closeToTray' in body) patch.closeToTray = Boolean(body.closeToTray);
    if ('autoLaunch' in body && runtime.autoLaunch?.supported) {
      runtime.autoLaunch.set(Boolean(body.autoLaunch));
    }
    await updateSettings(patch);
    if ('closeToTray' in patch) runtime.syncTray?.();
    return settingsPayload();
  });

  /** 일반 설정의 데이터 폴더·실행 형태 표시용. 포트/바인딩 변경 UI는 없다. */
  defineApi('server.info', 'admin', () => ({
    ...runtime.server?.info(),
    stateRoot: runtime.stateRoot,
    portable: runtime.portable,
  }));
}
