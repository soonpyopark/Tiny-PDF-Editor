/**
 * System tray — close-to-tray + right-click menu.
 *
 *   Update
 *   About
 *   Exit
 */
import { Menu, Tray, dialog, nativeImage, shell } from 'electron';
import fs from 'node:fs';
import {
  APP_NAME,
  APP_VERSION,
  UPDATE_REPO,
  formatAppBuildStamp,
} from '../shared/constants.js';
import { isUpdateAvailable, resolveUpdateKind, versionLabel } from '../shared/updateCheck.js';
import { fetchLatestRelease } from './updateService.js';

const RELEASES_PAGE_URL = UPDATE_REPO ? `https://github.com/${UPDATE_REPO}/releases` : '';

/**
 * @param {{
 *   resolveIconPath: () => string | undefined,
 *   getMainWindow: () => import('electron').BrowserWindow | null,
 *   focusMainWindow: () => void,
 *   quitApp: () => void,
 * }} options
 */
export function createTrayController(options) {
  /** @type {import('electron').Tray | null} */
  let tray = null;
  let updateBusy = false;

  function resolveTrayIcon() {
    const iconPath = options.resolveIconPath();
    if (iconPath && fs.existsSync(iconPath)) {
      const image = nativeImage.createFromPath(iconPath);
      if (!image.isEmpty()) {
        return image.resize({ width: 16, height: 16, quality: 'best' });
      }
    }
    return nativeImage.createEmpty();
  }

  function buildMenu() {
    return Menu.buildFromTemplate([
      {
        label: 'Update',
        click: () => {
          void checkForUpdatesFromTray();
        },
      },
      {
        label: 'About',
        click: () => {
          void showAboutFromTray();
        },
      },
      {
        label: 'Exit',
        click: () => {
          options.quitApp();
        },
      },
    ]);
  }

  function updateMenu() {
    if (!tray || tray.isDestroyed()) return;
    tray.setContextMenu(buildMenu());
  }

  async function showAboutFromTray() {
    const win = options.getMainWindow();
    const iconPath = options.resolveIconPath();
    const icon = iconPath && fs.existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : undefined;
    const box = {
      type: 'info',
      title: APP_NAME,
      message: APP_NAME,
      detail: `버전: v${APP_VERSION}\n빌드: ${formatAppBuildStamp()}\n라이선스: MIT License`,
      buttons: ['확인'],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
      ...(icon && !icon.isEmpty() ? { icon } : {}),
    };
    if (win && !win.isDestroyed()) await dialog.showMessageBox(win, box);
    else await dialog.showMessageBox(box);
  }

  async function checkForUpdatesFromTray() {
    if (updateBusy) return;
    updateBusy = true;
    try {
      const result = await fetchLatestRelease();
      const win = options.getMainWindow();
      const current = versionLabel(result.current);
      const parent = win && !win.isDestroyed() ? win : null;

      /** @param {import('electron').MessageBoxOptions} box */
      const show = (box) => (parent ? dialog.showMessageBox(parent, box) : dialog.showMessageBox(box));

      if (result.configured === false) {
        await show({
          type: 'info',
          title: '업데이트 확인',
          message: '업데이트 서버가 설정되지 않았습니다.',
          detail: `현재 버전: ${current} (${result.currentBuildStamp || formatAppBuildStamp()})\n\nshared/constants.js 의 UPDATE_REPO 에 GitHub 저장소(owner/repo)를 지정하면 릴리스 기준으로 확인합니다.`,
          buttons: ['확인'],
          defaultId: 0,
          cancelId: 0,
          noLink: true,
        });
        return;
      }

      if (!result.ok) {
        const box = {
          type: 'warning',
          title: '업데이트 확인',
          message: '업데이트 정보를 확인할 수 없습니다.',
          detail: `${result.error || '알 수 없는 오류'}\n\n현재 버전: ${current}`,
          buttons: RELEASES_PAGE_URL ? ['릴리스 페이지 열기', '닫기'] : ['닫기'],
          defaultId: 0,
          cancelId: RELEASES_PAGE_URL ? 1 : 0,
          noLink: true,
        };
        const response = await show(box);
        if (RELEASES_PAGE_URL && response.response === 0) {
          void shell.openExternal(RELEASES_PAGE_URL);
        }
        return;
      }

      if (isUpdateAvailable(result)) {
        const kind = resolveUpdateKind(result);
        const latest = versionLabel(result.latest || '');
        const stampHint =
          kind === 'build' && result.latestBuildStamp
            ? `\n최신 빌드: ${result.latestBuildStamp}`
            : '';
        const currentHint = result.currentBuildStamp
          ? `${current} (${result.currentBuildStamp})`
          : current;
        const box = {
          type: 'info',
          title: '업데이트 확인',
          message:
            kind === 'build'
              ? `같은 버전의 새 빌드가 있습니다: ${latest}`
              : `새 버전이 있습니다: ${latest}`,
          detail: `현재 버전: ${currentHint}${stampHint}`,
          buttons: ['다운로드', '나중에'],
          defaultId: 0,
          cancelId: 1,
          noLink: true,
        };
        const response = await show(box);
        if (response.response === 0) {
          void shell.openExternal(result.releaseUrl || RELEASES_PAGE_URL);
        }
        return;
      }

      const currentHint = result.currentBuildStamp
        ? `${current} (${result.currentBuildStamp})`
        : current;
      await show({
        type: 'info',
        title: '업데이트 확인',
        message: '최신 버전입니다.',
        detail: `현재 버전: ${currentHint}`,
        buttons: ['확인'],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      });
    } finally {
      updateBusy = false;
    }
  }

  function create() {
    if (tray && !tray.isDestroyed()) return;

    tray = new Tray(resolveTrayIcon());
    tray.setToolTip(APP_NAME);
    updateMenu();

    tray.on('double-click', () => {
      options.focusMainWindow();
    });
  }

  function destroy() {
    if (tray && !tray.isDestroyed()) {
      tray.destroy();
    }
    tray = null;
  }

  return { create, destroy, updateMenu };
}
