import { useEffect, useState } from 'react';

/** Matches pdf_editor.document.OPTIMIZE_DPI_CHOICES / OptimizeSizeOptions. */
export const OPTIMIZE_DPI_CHOICES = [36, 48, 72, 96, 120, 150, 200, 300, 400, 600];

const overlayClass =
  'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'w-full max-w-[420px] rounded-xl bg-white p-5 shadow-xl';
const labelClass = 'text-sm text-slate-700';
const fieldClass =
  'h-9 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-800 outline-none focus:border-app-accent';
const btnBase = 'rounded-full px-5 py-2 text-sm font-medium transition-colors';
const btnPrimary = `${btnBase} bg-app-accent text-white hover:bg-app-accentHover`;
const btnGhost = `${btnBase} text-slate-700 hover:bg-slate-100`;

/**
 * Tiny ReduceSizeDialog — dpi / quality / size percent.
 * @param {{ open: boolean, onClose: () => void, onApply: (options: { dpi: number, quality: number, sizePercent: number }) => void, sourceDpi?: number | null }} props
 */
export function ReduceSizeDialog({ open, onClose, onApply, sourceDpi = null }) {
  const [dpi, setDpi] = useState(150);
  const [quality, setQuality] = useState(100);
  const [sizePercent, setSizePercent] = useState(100);

  useEffect(() => {
    if (!open) return;
    setDpi(150);
    setQuality(100);
    setSizePercent(100);
  }, [open]);

  if (!open) return null;

  return (
    <div className={overlayClass} role="presentation" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="reduce-size-title"
        className={cardClass}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="reduce-size-title" className="m-0 text-lg font-medium text-slate-900">
          용량 줄이기
        </h2>
        <fieldset className="mt-4 rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-sm font-semibold text-slate-800">이미지 설정 조정</legend>
          <div className="grid gap-3">
            <label className={`grid gap-1 ${labelClass}`}>
              <span>
                이미지 압축 해상도
                {sourceDpi ? (
                  <span className="ml-1.5 text-xs text-slate-500" data-source-dpi={sourceDpi}>
                    (원본 : {sourceDpi}dpi)
                  </span>
                ) : null}
              </span>
              <select className={fieldClass} value={dpi} onChange={(e) => setDpi(Number(e.target.value))}>
                {OPTIMIZE_DPI_CHOICES.map((value) => (
                  <option key={value} value={value}>
                    {value}dpi
                  </option>
                ))}
              </select>
            </label>
            <label className={`grid gap-1 ${labelClass}`}>
              이미지 품질
              <input
                type="number"
                min={1}
                max={100}
                className={fieldClass}
                value={quality}
                onChange={(e) => setQuality(Math.min(100, Math.max(1, Number(e.target.value) || 1)))}
              />
            </label>
            <label className={`grid gap-1 ${labelClass}`}>
              이미지 사이즈
              <input
                type="number"
                min={1}
                max={100}
                className={fieldClass}
                value={sizePercent}
                onChange={(e) => setSizePercent(Math.min(100, Math.max(1, Number(e.target.value) || 1)))}
              />
            </label>
          </div>
          <p className="mt-3 m-0 text-[11px] leading-relaxed text-slate-500">
            압축 해상도만으로 원하는 용량에 도달하지 못할 때 품질·사이즈를 낮춰 추가로 줄일 수 있습니다.
          </p>
        </fieldset>
        <p className="mt-3 m-0 text-[11px] text-slate-500">진행 상태는 하단 상태 줄에 표시됩니다.</p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={btnGhost} onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className={btnPrimary}
            onClick={() => onApply({ dpi, quality, sizePercent })}
          >
            적용
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * 문서 탭 줄. 원본 Tiny의 탭 위치(에디터 최상단 전폭, 검색바는 오른쪽 끝)는 유지하되
 * 색·모양은 앱 테마 토큰(app-*)과 Tailwind 유틸리티로 새로 구성한다.
 */
export function DocumentTabBar({ docOpen, docName, modified, onClose, children }) {
  return (
    <div className="flex h-10 shrink-0 items-end gap-1 border-b border-app-border bg-app-surface px-2">
      {docOpen ? (
        <div
          role="tab"
          aria-selected="true"
          title={docName}
          className="relative -mb-px flex h-9 min-w-[120px] max-w-[260px] items-center gap-2 rounded-t-md border border-b-0 border-app-border bg-white pl-3 pr-1.5 text-[13px] text-slate-800 before:absolute before:inset-x-0 before:top-0 before:h-[2px] before:rounded-t-md before:bg-app-accent before:content-['']"
        >
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 shrink-0 text-app-accent" aria-hidden="true">
            <path
              d="M4 1.5h5.5L13 5v9.5H4z M9.5 1.5V5H13"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinejoin="round"
            />
          </svg>
          <span className="min-w-0 flex-1 truncate">{docName}</span>
          {modified ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-app-accent" title="수정됨" /> : null}
          <button
            type="button"
            title="닫기"
            aria-label="문서 닫기"
            className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
            onClick={onClose}
          >
            <svg viewBox="0 0 10 10" className="h-2.5 w-2.5" aria-hidden="true">
              <path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      ) : null}
      <div className="ml-auto flex h-full items-center pb-1.5 pr-1">{children}</div>
    </div>
  );
}

/** 검색어 강조: 결과 문장 안에서 찾은 검색어만 mark 로 감싼다. */
function HighlightedSnippet({ text, query }) {
  const needle = query.trim();
  if (!text) return null;
  const index = needle ? text.toLowerCase().indexOf(needle.toLowerCase()) : -1;
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded-sm bg-amber-200 px-0.5 text-slate-900">{text.slice(index, index + needle.length)}</mark>
      {text.slice(index + needle.length)}
    </>
  );
}

/**
 * Ctrl+F 검색 드롭다운 (문서 영역 오른쪽 위에서 펼쳐진다).
 * 1줄: 검색어 입력 + 이전/다음 + 닫기. 2줄: Enter 로 검색한 뒤 현재 결과의 쪽과 문장.
 */
export function SearchDropdown({
  query,
  ranQuery,
  hits,
  index,
  onQueryChange,
  onSubmit,
  onPrev,
  onNext,
  onClose,
  inputRef,
}) {
  const total = hits.length;
  const hit = total ? hits[index] : null;

  return (
    <div
      role="search"
      className="absolute right-3 top-2 z-30 w-[480px] max-w-[calc(100%-1.5rem)] overflow-hidden rounded-lg border border-app-border bg-white shadow-lg"
    >
      <div className="flex items-center gap-1.5 px-2.5 py-2">
        <input
          ref={inputRef}
          type="search"
          value={query}
          placeholder="텍스트 검색"
          title="Enter: 검색 / 다음 결과, Shift+Enter: 이전 결과, Esc: 닫기"
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              if (event.shiftKey && total) onPrev();
              else onSubmit();
            } else if (event.key === 'Escape') {
              event.preventDefault();
              onClose();
            }
          }}
          className="h-7 min-w-0 flex-1 rounded border border-slate-300 bg-white px-2 text-[13px] text-slate-800 outline-none focus:border-app-accent"
        />
        <button
          type="button"
          title="이전 결과 (Shift+Enter)"
          aria-label="이전 결과"
          disabled={!total}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded border border-slate-300 bg-white text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          onClick={onPrev}
        >
          ▲
        </button>
        <button
          type="button"
          title="다음 결과 (Enter)"
          aria-label="다음 결과"
          disabled={!total}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded border border-slate-300 bg-white text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          onClick={onNext}
        >
          ▼
        </button>
        <button
          type="button"
          title="검색 닫기 (Esc)"
          aria-label="검색 닫기"
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          onClick={onClose}
        >
          ×
        </button>
      </div>

      <div className="flex min-h-[32px] items-center gap-2 border-t border-app-border bg-slate-50 px-2.5 py-1.5 text-[12px] text-slate-600">
        {!ranQuery ? (
          <span className="text-slate-500">검색어를 입력하고 Enter를 누르세요.</span>
        ) : !hit ? (
          <span>‘{ranQuery}’ 검색 결과가 없습니다.</span>
        ) : (
          <>
            <span className="shrink-0 font-medium text-slate-700">
              검색 결과 [ {index + 1} / {total} ]
            </span>
            <span className="shrink-0 rounded border border-slate-200 bg-white px-1.5 py-px text-[11px] text-slate-600">
              {hit.pageIndex + 1}쪽
            </span>
            <span className="min-w-0 truncate text-slate-700">
              <HighlightedSnippet text={hit.snippet || ranQuery} query={ranQuery} />
            </span>
          </>
        )}
      </div>
    </div>
  );
}
