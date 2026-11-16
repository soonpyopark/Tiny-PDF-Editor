import { useEffect, useState } from 'react';
import { api } from '../../lib/apiClient.js';

/**
 * PDF 비밀번호 설정 대화상자 (Tiny password_dialog.py SetPasswordDialog 를 옮긴 것).
 * - 열기 비밀번호 + 확인 입력이 같아야 설정, 40자 이하
 * - 소유자 비밀번호는 비워 두면 열기 비밀번호와 같게 설정
 * - 각 입력칸 오른쪽 눈 아이콘으로 표시 / 숨기기
 * - 저장할 때 암호가 적용된다 (지금 바로 파일이 바뀌지는 않음)
 */

const MAX_PASSWORD_LENGTH = 40;
const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'w-full max-w-[420px] rounded-xl bg-white p-5 shadow-xl';
const labelClass = 'mb-1 block text-sm text-slate-700';
const fieldClass =
  'h-9 w-full rounded-md border border-slate-300 bg-white pl-2.5 pr-9 text-sm text-slate-800 outline-none focus:border-app-accent';
const btnBase = 'inline-flex h-9 items-center justify-center rounded-full px-5 text-sm font-medium transition-colors disabled:cursor-default disabled:opacity-50';
export const btnPrimary = `${btnBase} bg-app-accent text-white hover:bg-app-accentHover disabled:hover:bg-app-accent`;
export const btnGhost = `${btnBase} text-slate-700 hover:bg-slate-100`;
export const passwordOverlayClass = overlayClass;
export const passwordCardClass = cardClass;

function EyeIcon({ visible }) {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.3">
      <ellipse cx="8" cy="8" rx="6" ry="4" />
      <circle cx="8" cy="8" r="1.6" fill="currentColor" stroke="none" />
      {visible ? <path d="M2.5 13.5 13.5 2.5" strokeLinecap="round" /> : null}
    </svg>
  );
}

export function PasswordField({ id, label, value, onChange, placeholder, inputRef }) {
  const [visible, setVisible] = useState(false);
  return (
    <div>
      <label className={labelClass} htmlFor={id}>
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          ref={inputRef}
          type={visible ? 'text' : 'password'}
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          className={fieldClass}
          autoComplete="new-password"
        />
        <button
          type="button"
          className="absolute right-1.5 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          title={visible ? '비밀번호 숨기기' : '비밀번호 표시'}
          aria-label={visible ? '비밀번호 숨기기' : '비밀번호 표시'}
          onClick={() => setVisible((value) => !value)}
        >
          <EyeIcon visible={visible} />
        </button>
      </div>
    </div>
  );
}

/**
 * @param {{
 *   open: boolean,
 *   onClose: () => void,
 *   onApplied: (doc: any) => void,
 * }} props
 */
export default function PasswordSetDialog({ open, onClose, onApplied }) {
  const [userPassword, setUserPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [ownerPassword, setOwnerPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setUserPassword('');
    setConfirmPassword('');
    setOwnerPassword('');
    setError('');
    setBusy(false);
  }, [open]);

  if (!open) return null;

  function validate() {
    if (!userPassword) return '열기 비밀번호를 입력하세요.';
    if (userPassword.length > MAX_PASSWORD_LENGTH) return `비밀번호는 ${MAX_PASSWORD_LENGTH}자 이하여야 합니다.`;
    if (userPassword !== confirmPassword) return '비밀번호 확인이 일치하지 않습니다.';
    if (ownerPassword && ownerPassword.length > MAX_PASSWORD_LENGTH) {
      return `소유자 비밀번호는 ${MAX_PASSWORD_LENGTH}자 이하여야 합니다.`;
    }
    return '';
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const message = validate();
    if (message) {
      setError(message);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const result = await api('pdf.setPassword', {
        password: userPassword,
        ownerPassword: ownerPassword || undefined,
      });
      onApplied(result.doc);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '비밀번호를 설정하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={overlayClass} role="dialog" aria-modal="true" aria-label="PDF 비밀번호 설정">
      <form className={cardClass} onSubmit={submit}>
        <h2 className="mb-3 text-base font-semibold text-slate-900">PDF 비밀번호 설정</h2>
        <p className="mb-4 whitespace-pre-line text-xs leading-relaxed text-slate-500">
          {'저장할 때 PDF 열기 비밀번호가 적용됩니다.\n소유자 비밀번호는 비워 두면 열기 비밀번호와 같게 설정됩니다.'}
        </p>

        <div className="flex flex-col gap-3">
          <PasswordField id="pw-user" label="열기 비밀번호" value={userPassword} onChange={setUserPassword} />
          <PasswordField id="pw-confirm" label="비밀번호 확인" value={confirmPassword} onChange={setConfirmPassword} />
          <PasswordField
            id="pw-owner"
            label="소유자 비밀번호"
            value={ownerPassword}
            onChange={setOwnerPassword}
            placeholder="선택 사항"
          />
        </div>

        <p className="mt-3 min-h-[1.25rem] text-xs text-red-600" role="alert">
          {error}
        </p>

        <div className="mt-2 flex justify-end gap-2">
          <button type="button" className={btnGhost} onClick={onClose} disabled={busy}>
            취소
          </button>
          <button type="submit" className={btnPrimary} disabled={busy}>
            설정
          </button>
        </div>
      </form>
    </div>
  );
}
