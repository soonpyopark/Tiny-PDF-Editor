import { useEffect, useRef, useState } from 'react';
import { PasswordField, btnGhost, btnPrimary, passwordCardClass, passwordOverlayClass } from './PasswordSetDialog.jsx';

/**
 * PDF 비밀번호 확인 대화상자 (암호가 걸린 PDF를 열 때).
 * 비밀번호 설정 대화상자(PasswordSetDialog)와 같은 모양으로 맞춘다.
 * - 열기 비밀번호 한 칸, 눈 아이콘으로 표시 / 숨기기
 * - 틀리면 같은 창에서 다시 입력하게 한다
 * - 열릴 때와 틀렸을 때 입력창에 포커스를 둔다 (버튼 클릭 후에도 다시 입력창으로)
 *
 * @param {{
 *   open: boolean,
 *   rejected: boolean,
 *   onSubmit: (password: string) => void,
 *   onCancel: () => void,
 * }} props
 */
export default function PasswordOpenDialog({ open, rejected, onSubmit, onCancel }) {
  const [password, setPassword] = useState('');
  const inputRef = useRef(/** @type {HTMLInputElement | null} */ (null));

  useEffect(() => {
    if (!open) return;
    setPassword('');
  }, [open]);

  // 열리면 바로 입력창에 포커스. 틀려서 같은 창에 안내가 뜰 때도 다시 입력창으로 보낸다.
  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
  }, [open, rejected]);

  if (!open) return null;

  function submit(event) {
    event.preventDefault();
    if (!password) return;
    onSubmit(password);
  }

  return (
    <div className={passwordOverlayClass} role="dialog" aria-modal="true" aria-label="PDF 비밀번호 확인">
      <form className={passwordCardClass} onSubmit={submit}>
        <h2 className="mb-3 text-base font-semibold text-slate-900">PDF 비밀번호 확인</h2>
        <p className="mb-4 whitespace-pre-line text-xs leading-relaxed text-slate-500">
          {'이 PDF를 열려면 비밀번호가 필요합니다.\n열기 비밀번호를 입력하세요.'}
        </p>

        <div className="flex flex-col gap-3">
          <PasswordField
            id="pw-open"
            label="열기 비밀번호"
            value={password}
            onChange={setPassword}
            inputRef={inputRef}
          />
        </div>

        <p className="mt-3 min-h-[1.25rem] text-xs text-red-600" role="alert">
          {rejected ? '비밀번호가 올바르지 않습니다. 다시 입력해 주세요.' : ''}
        </p>

        <div className="mt-2 flex justify-end gap-2">
          <button type="button" className={btnGhost} onClick={onCancel}>
            취소
          </button>
          <button type="submit" className={btnPrimary} disabled={!password}>
            확인
          </button>
        </div>
      </form>
    </div>
  );
}
