import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

/**
 * App-styled replacements for window.alert / confirm.
 *
 *   const { alert, confirm, choose } = useDialog();
 *   if (await confirm({ title: '삭제', body: '삭제할까요?', confirmVariant: 'danger' })) { … }
 */

/**
 * @typedef {{
 *   title?: string,
 *   body?: string | import('react').ReactNode,
 *   confirmLabel?: string,
 *   cancelLabel?: string,
 *   confirmVariant?: 'primary' | 'danger',
 *   icon?: import('react').ReactNode,
 * }} DialogOptions
 *
 * @typedef {{
 *   title?: string,
 *   body?: string | import('react').ReactNode,
 *   primaryLabel?: string,
 *   secondaryLabel?: string,
 *   extraLabel?: string,
 *   cancelLabel?: string,
 * }} ChoiceOptions
 */

const DialogContext = createContext(
  /** @type {{
   *   alert: (options: DialogOptions) => Promise<void>,
   *   confirm: (options: DialogOptions) => Promise<boolean>,
   *   choose: (options: ChoiceOptions) => Promise<'primary' | 'secondary' | 'extra' | null>,
   * } | null} */ (null),
);

const btnBase = 'rounded-full px-5 py-2 text-sm font-medium transition-colors disabled:opacity-60';
const btnPrimary = `${btnBase} bg-app-accent text-white hover:bg-app-accentHover`;
const btnDanger = `${btnBase} bg-red-600 text-white hover:bg-red-700`;
const btnGhost = `${btnBase} text-slate-700 hover:bg-slate-100`;
const btnSoft = `${btnBase} bg-app-accentSoft text-app-accentText hover:bg-app-accentSoftHover`;

export function DialogProvider({ children }) {
  /** @type {[{ kind: 'alert' | 'confirm' | 'choose', options: any, resolve: (value: any) => void } | null, Function]} */
  const [dialog, setDialog] = useState(null);

  const open = useCallback(
    (kind, options) =>
      new Promise((resolve) => {
        setDialog({ kind, options: options ?? {}, resolve });
      }),
    [],
  );

  const alert = useCallback((options) => open('alert', options), [open]);
  const confirm = useCallback((options) => open('confirm', options), [open]);
  const choose = useCallback((options) => open('choose', options), [open]);

  const close = useCallback((result) => {
    setDialog((current) => {
      current?.resolve(result);
      return null;
    });
  }, []);

  const cancelResult = dialog?.kind === 'confirm' ? false : dialog?.kind === 'choose' ? null : undefined;

  useEffect(() => {
    if (!dialog) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') close(cancelResult);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [dialog, close, cancelResult]);

  const value = useMemo(() => ({ alert, confirm, choose }), [alert, confirm, choose]);
  const options = dialog?.options ?? {};

  return (
    <DialogContext.Provider value={value}>
      {children}
      {dialog ? (
        <div
          className="fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4"
          role="presentation"
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="app-dialog-title"
            className={`w-full rounded-xl bg-white p-6 shadow-xl ${options.secondaryLabel ? 'max-w-[560px]' : 'max-w-[440px]'}`}
          >
            <div className={options.icon ? 'flex items-start gap-4' : ''}>
              {options.icon ? <div className="shrink-0">{options.icon}</div> : null}
              <div className="min-w-0 flex-1">
                <h2 id="app-dialog-title" className="m-0 text-lg font-medium text-slate-900">
                  {options.title ?? (dialog.kind === 'confirm' ? '확인' : '알림')}
                </h2>
                <div className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-600">
                  {options.body}
                </div>
              </div>
            </div>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              {dialog.kind === 'alert' ? (
                <button type="button" autoFocus className={btnPrimary} onClick={() => close(undefined)}>
                  {options.confirmLabel ?? '확인'}
                </button>
              ) : null}
              {dialog.kind === 'confirm' ? (
                <>
                  <button type="button" className={btnGhost} onClick={() => close(false)}>
                    {options.cancelLabel ?? '취소'}
                  </button>
                  <button
                    type="button"
                    autoFocus
                    className={options.confirmVariant === 'danger' ? btnDanger : btnPrimary}
                    onClick={() => close(true)}
                  >
                    {options.confirmLabel ?? '확인'}
                  </button>
                </>
              ) : null}
              {dialog.kind === 'choose' ? (
                <>
                  <button type="button" className={btnGhost} onClick={() => close(null)}>
                    {options.cancelLabel ?? '취소'}
                  </button>
                  {options.extraLabel ? (
                    <button type="button" className={btnSoft} onClick={() => close('extra')}>
                      {options.extraLabel}
                    </button>
                  ) : null}
                  {options.secondaryLabel ? (
                    <button type="button" className={btnSoft} onClick={() => close('secondary')}>
                      {options.secondaryLabel}
                    </button>
                  ) : null}
                  <button type="button" autoFocus className={btnPrimary} onClick={() => close('primary')}>
                    {options.primaryLabel ?? '확인'}
                  </button>
                </>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </DialogContext.Provider>
  );
}

export function useDialog() {
  const context = useContext(DialogContext);
  if (!context) throw new Error('useDialog must be used within DialogProvider');
  return context;
}
