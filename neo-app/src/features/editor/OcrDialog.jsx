import { useState, useEffect } from 'react';

/**
 * OCR 옵션 대화상자.
 * - indices 가 null 이면 전체 페이지, 배열이면 썸네일에서 고른 페이지만 OCR.
 * - 범위를 정하고 "변환하기"를 누르면 onApply 콜백에 { scope, pageFrom?, pageTo? } 를 넘긴다.
 */

const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'flex w-full max-w-[420px] flex-col rounded-xl bg-white p-5 shadow-xl';
const labelClass = 'whitespace-nowrap text-sm text-slate-700';
const fieldBase =
  'h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-800 outline-none focus:border-app-accent disabled:opacity-50';
const btnBase = 'inline-flex h-9 items-center justify-center rounded-full px-5 text-sm font-medium transition-colors disabled:cursor-default disabled:opacity-50';
const btnPrimary = `${btnBase} bg-app-accent text-white hover:bg-app-accentHover disabled:hover:bg-app-accent`;
const btnGhost = `${btnBase} border border-slate-300 text-slate-700 hover:bg-slate-100`;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function defaultForm(pageCount) {
  return {
    scope: 'current', // 'current' | 'selected' | 'all' | 'range'
    pageFrom: 1,
    pageTo: Math.max(1, pageCount),
  };
}

export default function OcrDialog({ open, pageCount, indices, onClose, onApply }) {
  const [form, setForm] = useState(() => defaultForm(pageCount));
  const selected = Array.isArray(indices) ? indices : null;
  const selectedCount = selected ? selected.length : 0;

  useEffect(() => {
    if (open) setForm(defaultForm(pageCount));
  }, [open, pageCount]);

  if (!open) return null;

  const pages = Math.max(1, pageCount);
  const set = (patch) => setForm((prev) => ({ ...prev, ...patch }));

  function setFrom(value) {
    const from = clamp(value, 1, pages);
    setForm((prev) => ({ ...prev, pageFrom: from, pageTo: Math.max(prev.pageTo, from) }));
  }

  function setTo(value) {
    const to = clamp(value, 1, pages);
    setForm((prev) => ({ ...prev, pageTo: to, pageFrom: Math.min(prev.pageFrom, to) }));
  }

  function submit(event) {
    event.preventDefault();
    const payload = { scope: form.scope };
    if (form.scope === 'range') {
      payload.pageFrom = form.pageFrom;
      payload.pageTo = form.pageTo;
    }
    onApply(payload);
  }

  return (
    <div className={overlayClass} role="presentation">
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="ocr-title"
        className={cardClass}
        onSubmit={submit}
      >
        <h2 id="ocr-title" className="m-0 text-base font-semibold text-slate-900">
          OCR 변환하기
        </h2>

        <div className="mt-4 flex flex-col gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="radio"
              name="scope"
              value="current"
              checked={form.scope === 'current'}
              onChange={() => set({ scope: 'current' })}
              className="h-4 w-4 accent-app-accent"
            />
            현재 페이지
          </label>

          {selectedCount > 0 && (
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="radio"
                name="scope"
                value="selected"
                checked={form.scope === 'selected'}
                onChange={() => set({ scope: 'selected' })}
                className="h-4 w-4 accent-app-accent"
              />
              선택한 {selectedCount}개 페이지
            </label>
          )}

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="radio"
              name="scope"
              value="all"
              checked={form.scope === 'all'}
              onChange={() => set({ scope: 'all' })}
              className="h-4 w-4 accent-app-accent"
            />
            전체 페이지
          </label>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="radio"
              name="scope"
              value="range"
              checked={form.scope === 'range'}
              onChange={() => set({ scope: 'range' })}
              className="h-4 w-4 accent-app-accent"
            />
            범위
          </label>

          {form.scope === 'range' && (
            <div className="ml-6 flex gap-2 text-sm">
              <div className="flex items-center gap-1">
                <label className={labelClass}>쪽</label>
                <input
                  type="number"
                  min={1}
                  max={pages}
                  value={form.pageFrom}
                  disabled={form.scope !== 'range'}
                  className={fieldBase}
                  onChange={(event) => setFrom(clamp(Math.trunc(Number(event.target.value)) || 0, 1, pages))}
                />
              </div>
              <span className="flex items-center text-slate-600">~</span>
              <div className="flex items-center gap-1">
                <label className={labelClass}>쪽</label>
                <input
                  type="number"
                  min={1}
                  max={pages}
                  value={form.pageTo}
                  disabled={form.scope !== 'range'}
                  className={fieldBase}
                  onChange={(event) => setTo(clamp(Math.trunc(Number(event.target.value)) || 0, 1, pages))}
                />
              </div>
            </div>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button type="submit" className={btnPrimary}>
            변환하기
          </button>
          <button type="button" className={btnGhost} onClick={onClose}>
            취소
          </button>
        </div>
      </form>
    </div>
  );
}
