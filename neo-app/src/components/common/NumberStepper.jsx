import { useEffect, useRef, useState } from 'react';

function formatNumber(value) {
  return String(Math.round(Number(value) * 100) / 100);
}

/**
 * 숫자 입력 칸 + 줄이기/늘리기 단추. 슬라이더보다 좁고 정확한 값을 넣을 수 있다.
 * - 칸에 직접 입력하고 Enter·다른 곳 누르기로 확정한다. (입력하는 중에는 범위를 고치지 않고, 확정할 때 normalize 로 맞춘다.)
 * - 단추, 칸에서 ↑↓ 키, 칸에 포커스가 있을 때의 마우스 휠은 step 만큼 바꾼다. Esc 는 입력을 취소한다.
 */
export default function NumberStepper({ label, title, ariaLabel, dataAttr, suffix, value, min, max, step, normalize, onChange }) {
  const [text, setText] = useState(formatNumber(value));
  const focusedRef = useRef(false);
  useEffect(() => {
    if (!focusedRef.current) setText(formatNumber(value));
  }, [value]);

  const apply = (next) => {
    const fixed = normalize(next);
    setText(formatNumber(fixed));
    if (fixed !== value) onChange(fixed);
  };
  const commit = (raw) => {
    const number = Number(String(raw).trim().replace(',', '.'));
    if (!String(raw).trim() || !Number.isFinite(number)) {
      setText(formatNumber(value));
      return;
    }
    apply(number);
  };
  const bump = (direction) => apply(value + direction * step);
  const stepButton =
    'h-7 w-5 select-none text-[14px] leading-none text-slate-600 hover:bg-slate-100 disabled:cursor-default disabled:text-slate-300 disabled:hover:bg-transparent';

  return (
    <div className="flex items-center gap-1" title={title || label}>
      <span className="text-slate-500">{label}</span>
      <span className="inline-flex items-center overflow-hidden rounded border border-slate-300 bg-white focus-within:border-app-accent">
        <button type="button" tabIndex={-1} aria-label={`${ariaLabel || label} 줄이기`} disabled={value <= min} onClick={() => bump(-1)} className={stepButton}>
          −
        </button>
        <input
          type="text"
          inputMode="decimal"
          value={text}
          aria-label={ariaLabel || label}
          {...{ [dataAttr || 'data-draw-number']: '1' }}
          onChange={(event) => setText(event.target.value)}
          onFocus={(event) => {
            focusedRef.current = true;
            event.currentTarget.select();
          }}
          onBlur={(event) => {
            focusedRef.current = false;
            commit(event.currentTarget.value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              commit(event.currentTarget.value);
              event.currentTarget.select();
            } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
              event.preventDefault();
              bump(event.key === 'ArrowUp' ? 1 : -1);
            } else if (event.key === 'Escape') {
              event.preventDefault();
              event.stopPropagation();
              setText(formatNumber(value));
              event.currentTarget.blur();
            }
          }}
          onWheel={(event) => {
            if (document.activeElement !== event.currentTarget) return;
            bump(event.deltaY < 0 ? 1 : -1);
          }}
          className="h-7 w-10 border-x border-slate-200 bg-transparent px-1 text-center tabular-nums outline-none"
        />
        <button type="button" tabIndex={-1} aria-label={`${ariaLabel || label} 늘리기`} disabled={value >= max} onClick={() => bump(1)} className={stepButton}>
          +
        </button>
      </span>
      {suffix ? <span className="text-slate-400">{suffix}</span> : null}
    </div>
  );
}
