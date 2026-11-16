import { getNative } from './apiClient.js';

/** Opens a URL in the OS browser (Electron) or a new tab (plain browser). */
export async function openExternalUrl(url) {
  const native = getNative();
  if (native?.openExternal) {
    await native.openExternal(url);
    return;
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}
