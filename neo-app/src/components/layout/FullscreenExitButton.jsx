import { useEffect, useRef, useState } from 'react';
import { exitFullscreen, useFullscreen } from '../../lib/fullscreen.js';

/** 마우스가 이 높이(px) 안으로 올라오면 종료 버튼을 보여 준다 (원본 reveal_band). */
const REVEAL_BAND = 80;
/** 버튼이 내려와 있는 동안, 버튼 주변(좌우·아래 여유 포함)에 마우스가 있으면 사라지지 않는다. */
const KEEP_HALF_WIDTH = 90;
const KEEP_BOTTOM = 150;
/** 마우스가 영역을 벗어난 뒤 이 시간(ms)이 지나야 사라진다. 내려오는 동안 마우스가 앞서 가도 버튼이 도망가지 않게 한다. */
const HIDE_DELAY = 700;

/**
 * 전체화면 종료 버튼 (원본 Tiny: fullscreenExitBtn).
 * 마우스를 화면 맨 위로 올리면 위에서 내려오고, 벗어나면 잠시 뒤 사라진다. 크롬의 동그라미 X 와 같다.
 */
export default function FullscreenExitButton() {
  const fullscreen = useFullscreen();
  const [visible, setVisible] = useState(false);
  const visibleRef = useRef(false);
  const hoverRef = useRef(false);
  const hideTimer = useRef(0);

  useEffect(() => {
    const show = (value) => {
      visibleRef.current = value;
      setVisible(value);
    };
    const cancelHide = () => {
      if (hideTimer.current) window.clearTimeout(hideTimer.current);
      hideTimer.current = 0;
    };
    const scheduleHide = () => {
      if (hideTimer.current || !visibleRef.current) return;
      hideTimer.current = window.setTimeout(() => {
        hideTimer.current = 0;
        if (!hoverRef.current) show(false);
      }, HIDE_DELAY);
    };
    if (!fullscreen) {
      cancelHide();
      show(false);
      hoverRef.current = false;
      return undefined;
    }
    const onMove = (event) => {
      const centerX = window.innerWidth / 2;
      const inBand = event.clientY >= 0 && event.clientY <= REVEAL_BAND;
      const nearButton =
        visibleRef.current &&
        Math.abs(event.clientX - centerX) <= KEEP_HALF_WIDTH &&
        event.clientY >= 0 &&
        event.clientY <= KEEP_BOTTOM;
      if (hoverRef.current || inBand || nearButton) {
        cancelHide();
        if (!visibleRef.current) show(true);
      } else {
        scheduleHide();
      }
    };
    const onLeave = () => {
      if (!hoverRef.current) scheduleHide();
    };
    window.addEventListener('mousemove', onMove);
    document.addEventListener('mouseleave', onLeave);
    return () => {
      cancelHide();
      window.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseleave', onLeave);
    };
  }, [fullscreen]);

  if (!fullscreen) return null;

  return (
    <button
      type="button"
      title="전체 화면 해제 (ESC)"
      aria-label="전체 화면 해제"
      tabIndex={-1}
      onMouseEnter={() => {
        hoverRef.current = true;
      }}
      onMouseLeave={() => {
        hoverRef.current = false;
      }}
      onClick={exitFullscreen}
      className={`fixed left-1/2 top-16 z-[3000] flex h-[38px] w-[38px] -translate-x-1/2 items-center justify-center rounded-full border-0 bg-[rgba(70,70,70,0.82)] text-white transition-[translate,opacity,background-color] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] hover:bg-[rgba(20,20,20,0.92)] ${
        visible ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-[130px] opacity-0'
      }`}
    >
      <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
        <line x1="3.5" y1="3.5" x2="12.5" y2="12.5" />
        <line x1="12.5" y1="3.5" x2="3.5" y2="12.5" />
      </svg>
    </button>
  );
}
