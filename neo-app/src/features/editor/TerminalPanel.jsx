import { useEffect, useRef } from 'react';

/**
 * 원본 Tiny PDF Editor 하단 "터미널" 패널. OCR·용량 줄이기·개인정보 제거처럼
 * 시간이 걸리는 작업의 진행 로그를 보여 준다. 닫기 전까지 펼침/접힘을 유지한다.
 */
export default function TerminalPanel({ open, expanded, lines, onToggleExpanded, onClose }) {
  const bodyRef = useRef(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  if (!open) return null;

  return (
    <section aria-label="터미널" className="shrink-0 border-t border-app-border bg-[#1e1e1e] text-[#d4d4d4]">
      <header className="flex h-8 items-center justify-between px-2">
        <button
          type="button"
          onClick={onToggleExpanded}
          className="inline-flex h-6 items-center gap-1 rounded px-2 text-[12px] font-medium text-[#cccccc] hover:bg-white/10"
          aria-expanded={expanded}
        >
          {expanded ? '▼' : '▶'} 터미널
        </button>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-6 w-6 items-center justify-center rounded text-[14px] text-[#cccccc] hover:bg-white/10"
          aria-label="터미널 닫기"
          title="터미널 닫기"
        >
          ×
        </button>
      </header>
      {expanded ? (
        <pre
          ref={bodyRef}
          className="m-0 h-40 overflow-auto whitespace-pre-wrap break-words px-3 pb-2 font-mono text-[12px] leading-5"
        >
          {lines.join('\n')}
        </pre>
      ) : null}
    </section>
  );
}
