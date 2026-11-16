import { useEffect, useState } from 'react';

/**
 * 이미지로 저장 옵션 대화상자 (Tiny export_images_dialog.py ExportImagesDialog 를 옮긴 것).
 * - indices 가 null 이면 문서 전체(페이지 범위 입력 있음), 배열이면 썸네일에서 고른 페이지만 저장.
 * - 옵션을 확인한 뒤 "폴더 선택..." 으로 넘긴다. 폴더 선택/덮어쓰기 확인은 Electron 쪽에서 한다.
 */

const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'flex w-full max-w-[460px] flex-col rounded-xl bg-white p-5 shadow-xl';
const labelClass = 'whitespace-nowrap text-sm text-slate-700';
const fieldBase =
  'h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-800 outline-none focus:border-app-accent disabled:opacity-50';
const btnBase = 'inline-flex h-9 items-center justify-center rounded-full px-5 text-sm font-medium transition-colors disabled:cursor-default disabled:opacity-50';
const btnPrimary = `${btnBase} bg-app-accent text-white hover:bg-app-accentHover disabled:hover:bg-app-accent`;
const btnGhost = `${btnBase} border border-slate-300 text-slate-700 hover:bg-slate-100`;

/** export_images_dialog.EXPORT_DPI_CHOICES / _DEFAULT_DPI 와 같다. */
const DPI_CHOICES = [72, 100, 150, 200, 300, 600];
const DEFAULT_DPI = 150;
const DEFAULT_JPEG_QUALITY = 92;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function defaultForm(pageCount) {
  return {
    dpi: DEFAULT_DPI,
    format: 'png',
    jpegQuality: DEFAULT_JPEG_QUALITY,
    pageFrom: 1,
    pageTo: Math.max(1, pageCount),
    includeAnnotations: true,
  };
}

/** 원본 page_filename_width: 전체 쪽 수 자릿수만큼 0 으로 채운다. */
function padWidth(pageCount) {
  return Math.max(1, String(Math.max(1, pageCount)).length);
}

export default function ExportImagesDialog({ open, pageCount, indices, onClose, onApply }) {
  const [form, setForm] = useState(() => defaultForm(pageCount));
  const selected = Array.isArray(indices) ? indices : null;
  const selectedCount = selected ? selected.length : 0;

  useEffect(() => {
    if (open) setForm(defaultForm(pageCount));
  }, [open, pageCount]);

  if (!open) return null;

  const pages = Math.max(1, pageCount);
  const isJpeg = form.format === 'jpeg';
  const set = (patch) => setForm((prev) => ({ ...prev, ...patch }));

  // 원본 _sync_page_range: 시작이 끝보다 크면 끝을 같이 올리고, 끝이 시작보다 작으면 시작을 같이 내린다.
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
    const payload = {
      dpi: form.dpi,
      format: form.format,
      jpegQuality: form.jpegQuality,
      includeAnnotations: form.includeAnnotations,
    };
    if (!selected) {
      payload.pageFrom = form.pageFrom;
      payload.pageTo = form.pageTo;
    }
    onApply(payload);
  }

  const width = padWidth(pageCount);
  const summary = selected
    ? `선택한 ${selectedCount}개 페이지를 저장합니다.`
    : `총 ${pageCount}페이지를 저장합니다.`;

  return (
    <div className={overlayClass} role="presentation">
      <form role="dialog" aria-modal="true" aria-labelledby="export-images-title" className={cardClass} onSubmit={submit}>
        <h2 id="export-images-title" className="m-0 text-base font-semibold text-slate-900">
          이미지로 저장
        </h2>
        <p className="mt-2 text-sm text-slate-500">{summary}</p>

        <fieldset className="mt-4 grid grid-cols-[120px_1fr] items-center gap-x-3 gap-y-2.5 rounded-lg border border-slate-200 p-4">
          <legend className="px-1 text-sm font-semibold text-slate-800">저장 옵션</legend>

          <span className={labelClass}>해상도:</span>
          <select className={`${fieldBase} w-32`} value={form.dpi} onChange={(e) => set({ dpi: Number(e.target.value) })}>
            {DPI_CHOICES.map((dpi) => (
              <option key={dpi} value={dpi}>
                {dpi} DPI
              </option>
            ))}
          </select>

          <span className={labelClass}>이미지 형식:</span>
          <select className={`${fieldBase} w-32`} value={form.format} onChange={(e) => set({ format: e.target.value })}>
            <option value="png">PNG</option>
            <option value="jpeg">JPEG</option>
          </select>

          <span className={labelClass}>JPEG 품질:</span>
          <span className="flex items-center gap-1">
            <input
              type="number"
              min={1}
              max={100}
              value={form.jpegQuality}
              disabled={!isJpeg}
              onChange={(e) => set({ jpegQuality: clamp(Math.trunc(Number(e.target.value)) || 1, 1, 100) })}
              className={`${fieldBase} w-20`}
            />
            <span className="text-sm text-slate-500">%</span>
          </span>

          {selected ? null : (
            <>
              <span className={labelClass}>페이지 범위:</span>
              <span className="flex items-center gap-2">
                <span className="text-sm text-slate-500">시작</span>
                <input
                  type="number"
                  min={1}
                  max={pages}
                  value={form.pageFrom}
                  onChange={(e) => setFrom(Math.trunc(Number(e.target.value)) || 1)}
                  className={`${fieldBase} w-20`}
                />
                <span className="text-sm text-slate-500">~</span>
                <input
                  type="number"
                  min={1}
                  max={pages}
                  value={form.pageTo}
                  onChange={(e) => setTo(Math.trunc(Number(e.target.value)) || 1)}
                  className={`${fieldBase} w-20`}
                />
                <span className="text-sm text-slate-500">끝</span>
              </span>
            </>
          )}

          <span />
          <label className="flex items-center gap-2 whitespace-nowrap text-sm text-slate-700">
            <input
              type="checkbox"
              checked={form.includeAnnotations}
              onChange={(e) => set({ includeAnnotations: e.target.checked })}
            />
            주석(형광펜·밑줄 등) 포함
          </label>

          {selected ? null : (
            <>
              <span />
              <span className="text-xs text-slate-500">
                파일 이름 예: {String(1).padStart(width, '0')}.{isJpeg ? 'jpg' : 'png'} …{' '}
                {String(pages).padStart(width, '0')}.{isJpeg ? 'jpg' : 'png'}
              </span>
            </>
          )}
        </fieldset>

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={btnGhost} onClick={onClose}>
            취소
          </button>
          <button type="submit" className={btnPrimary}>
            폴더 선택...
          </button>
        </div>
      </form>
    </div>
  );
}
