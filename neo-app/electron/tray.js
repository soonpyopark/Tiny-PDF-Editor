/**
 * System tray — close-to-tray + right-click menu.
 *
 *   About
 *   Exit
 */
import { Menu, Tray, dialog, nativeImage } from 'electron';
import fs from 'node:fs';
import { APP_NAME, APP_VERSION, formatAppBuildStamp } from '../shared/constants.js';

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

  function isActive() {
    return Boolean(tray && !tray.isDestroyed());
  }

  return { create, destroy, updateMenu, isActive };
}
