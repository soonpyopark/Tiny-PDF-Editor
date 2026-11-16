import { useEffect, useRef, useState } from 'react';
import { exitFullscreen, useFullscreen } from '../../lib/fullscreen.js';

/** 마우스가 이 높이(px) 안으로 올라오면 종료 버튼을 보여 준다 (원본 reveal_band). */
const REVEAL_BAND = 60;

/**
 * 전체화면 종료 버튼 (원본 Tiny: fullscreenExitBtn).
 * 마우스를 화면 맨 위로 올리면 위에서 내려오고, 벗어나면 사라진다. 크롬의 동그라미 X 와 같다.
 */
export default function FullscreenExitButton() {
  const fullscreen = useFullscreen();
  const [visible, setVisible] = useState(false);
  const hoverRef = useRef(false);

  useEffect(() => {
    if (!fullscreen) {
      setVisible(false);
      hoverRef.current = false;
      return undefined;
    }
    const onMove = (event) => {
      // 버튼 위에 있는 동안은 대역을 벗어나도 유지한다 (버튼이 대역 아래까지 걸친다).
      setVisible(hoverRef.current || (event.clientY >= 0 && event.clientY <= REVEAL_BAND));
    };
    const onLeave = () => {
      if (!hoverRef.current) setVisible(false);
    };
    window.addEventListener('mousemove', onMove);
    document.addEventListener('mouseleave', onLeave);
    return () => {
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
      className={`fixed left-1/2 top-7 z-[3000] flex h-[34px] w-[34px] -translate-x-1/2 items-center justify-center rounded-full border-0 bg-[rgba(70,70,70,0.82)] text-white transition-[transform,opacity] duration-200 ease-out hover:bg-[rgba(20,20,20,0.92)] ${
        visible ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-[90px] opacity-0'
      }`}
    >
      <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
        <line x1="3.5" y1="3.5" x2="12.5" y2="12.5" />
        <line x1="12.5" y1="3.5" x2="3.5" y2="12.5" />
      </svg>
    </button>
  );
}
