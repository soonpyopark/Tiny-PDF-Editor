const { contextBridge, ipcRenderer, webUtils } = require('electron');

/**
 * Native bridge for the Electron window. Everything else goes over the HTTP
 * API (src/lib/apiClient.js), so the same UI also works in a LAN browser, where
 * `window.frame` is simply undefined.
 */
contextBridge.exposeInMainWorld('frame', {
  isElectron: true,  getInfo: () => ipcRenderer.invoke('frame:getInfo'),
  openExternal: (url) => ipcRenderer.invoke('frame:openExternal', url),
  openStateFolder: (sub) => ipcRenderer.invoke('frame:openStateFolder', sub),
  quit: () => ipcRenderer.invoke('frame:quit'),
  /** 도움말 > 정보: 스플래시 형태의 정보 창을 연다/닫는다. */
  showAboutSplash: () => ipcRenderer.invoke('frame:showAboutSplash'),
  /** Real path of a dropped File (sandboxed pages cannot read File.path). */
  pathForFile: (file) => webUtils.getPathForFile(file),
  /** 엔진 진행 로그 구독. 해제 함수를 돌려준다. */
  onPdfLog: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('pdf:log', listener);
    return () => ipcRenderer.removeListener('pdf:log', listener);
  },
  /** 새 문서 창을 열고 파일 경로를 넘긴다. */
  openDocumentWindow: (filePath) => ipcRenderer.invoke('frame:openDocumentWindow', filePath),
});
