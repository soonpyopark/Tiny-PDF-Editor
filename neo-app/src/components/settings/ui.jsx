/** Small building blocks shared by the settings panels. */

export const inputClass =
  'w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-app-accent focus:ring-2 focus:ring-app-accent/15 disabled:bg-slate-50 disabled:text-slate-400';

export const btnClass =
  'inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50';

export const btnPrimaryClass =
  'inline-flex items-center justify-center gap-1.5 rounded-md border border-transparent bg-app-accent px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-app-accentHover disabled:opacity-50';

export const btnDangerClass =
  'inline-flex items-center justify-center gap-1.5 rounded-md border border-red-200 bg-white px-3 py-1.5 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50';

export const codeClass = 'rounded bg-slate-100 px-1 text-[12px]';

/** @param {{ title: string, description?: import('react').ReactNode, children: import('react').ReactNode, actions?: import('react').ReactNode }} props */
export function Section({ title, description, children, actions }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="m-0 text-sm font-semibold text-slate-900">{title}</h3>
          {description ? (
            <p className="mt-1 text-sm leading-relaxed text-slate-500">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 gap-2">{actions}</div> : null}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/**
 * Switch row: label + hint on the left, toggle on the right.
 *
 * @param {{
 *   label: string,
 *   hint?: import('react').ReactNode,
 *   checked: boolean,
 *   disabled?: boolean,
 *   onChange: (checked: boolean) => void,
 * }} props
 */
export function ToggleRow({ label, hint, checked, disabled = false, onChange }) {
  return (
    <label
      className={`flex items-center justify-between gap-4 py-2 ${disabled ? 'opacity-60' : 'cursor-pointer'}`}
    >
      <span className="min-w-0">
        <span className="block text-sm font-medium text-slate-800">{label}</span>
        {hint ? <span className="mt-0.5 block text-xs leading-snug text-slate-500">{hint}</span> : null}
      </span>
      <span className="relative inline-flex h-6 w-11 shrink-0 items-center">
        <input
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="absolute inset-0 rounded-full bg-slate-300 transition-colors peer-checked:bg-app-accent peer-focus-visible:ring-2 peer-focus-visible:ring-app-accent/40" />
        <span className="absolute left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-5" />
      </span>
    </label>
  );
}

/** @param {{ label: string, hint?: string, children: import('react').ReactNode }} props */
export function Field({ label, hint, children }) {
  return (
    <label className="flex flex-col gap-2">
      <span className="block text-xs font-medium text-slate-600">{label}</span>
      {children}
      {hint ? <span className="block text-xs leading-relaxed text-slate-400">{hint}</span> : null}
    </label>
  );
}

/** @param {{ children: import('react').ReactNode, tone?: 'default' | 'green' | 'amber' | 'red' | 'slate' }} props */
export function Badge({ children, tone = 'default' }) {
  const tones = {
    default: 'bg-app-accentSoft text-app-accentText',
    green: 'bg-emerald-50 text-emerald-700',
    amber: 'bg-amber-50 text-amber-700',
    red: 'bg-red-50 text-red-700',
    slate: 'bg-slate-100 text-slate-600',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** @param {{ message: string }} props */
export function Loading({ message = '불러오는 중…' }) {
  return <p className="text-sm text-slate-500">{message}</p>;
}

/** @param {{ message: string, onRetry?: () => void }} props */
export function LoadError({ message, onRetry }) {
  return (
    <div className="space-y-2">
      <p className="text-sm text-red-600">{message}</p>
      {onRetry ? (
        <button type="button" className={btnClass} onClick={onRetry}>
          다시 시도
        </button>
      ) : null}
    </div>
  );
}
