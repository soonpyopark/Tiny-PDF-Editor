/**
 * 스플래시 창 전용 preload: 클릭·Esc 입력을 메인 프로세스에 알린다.
 * 링크를 누른 경우에는 닫지 않는다.
 */
const { ipcRenderer } = require('electron');

window.addEventListener('DOMContentLoaded', () => {
  document.addEventListener('mousedown', (event) => {
    const target = event.target;
    if (target instanceof Element && target.closest('a')) return;
    ipcRenderer.send('splash:dismiss');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') ipcRenderer.send('splash:dismiss');
  });
});
