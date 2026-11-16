import { useEffect, useState } from 'react';

/**
 * 앱 전체화면: 브라우저 전체화면(Electron 에서는 창 전체화면)이 유일한 기준이다.
 * 메뉴 > 보기 > 전체 화면, F11, 종료 버튼이 모두 같은 상태를 본다.
 */

export function isFullscreen() {
  return Boolean(document.fullscreenElement);
}

export function enterFullscreen() {
  if (isFullscreen()) return;
  void document.documentElement.requestFullscreen?.().catch(() => undefined);
}

export function exitFullscreen() {
  if (!isFullscreen()) return;
  void document.exitFullscreen?.().catch(() => undefined);
}

export function toggleFullscreen() {
  if (isFullscreen()) exitFullscreen();
  else enterFullscreen();
}

/** 전체화면 여부. 전체화면이 바뀔 때마다 다시 그린다. */
export function useFullscreen() {
  const [fullscreen, setFullscreen] = useState(isFullscreen);
  useEffect(() => {
    const onChange = () => setFullscreen(isFullscreen());
    document.addEventListener('fullscreenchange', onChange);
    onChange();
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);
  return fullscreen;
}
