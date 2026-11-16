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
  /** 창 닫기·종료 요청이 오면 handler 를 부른다. 저장 여부를 묻고 respondClose 로 답한다. */
  onCloseRequest: (handler) => {
    const listener = () => handler();
    ipcRenderer.on('frame:closeRequest', listener);
    return () => ipcRenderer.removeListener('frame:closeRequest', listener);
  },
  respondClose: (proceed) => ipcRenderer.send('frame:closeResponse', proceed === true),
  /**
   * 앱 밖에서 넘어온 파일(인쇄 PDF, 연결 프로그램으로 연 파일)을 받는다.
   * 구독하면 준비됐다고 메인에 알리고, 그동안 쌓인 경로도 이어서 받는다.
   */
  onOpenPaths: (handler) => {
    const listener = (_event, paths) => handler(Array.isArray(paths) ? paths : []);
    ipcRenderer.on('frame:openPaths', listener);
    ipcRenderer.send('frame:openPathsReady');
    return () => ipcRenderer.removeListener('frame:openPaths', listener);
  },
});
