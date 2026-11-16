import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/apiClient.js';
import { useAppInfo } from '../../context/AppInfoContext.jsx';
import { useAuth } from '../../context/AuthContext.jsx';
import AppLogo from '../common/AppLogo.jsx';

const fieldClass =
  'w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-app-accent focus:ring-2 focus:ring-app-accent/15';

function PasswordVisibilityIcon({ visible }) {
  if (visible) {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path
          fill="currentColor"
          d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5C21.27 7.61 17 4.5 12 4.5zm0 12.5c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 7c2.76 0 5 2.24 5 5 0 .65-.13 1.26-.36 1.83l2.92 2.92c1.51-1.26 2.7-2.89 3.43-4.75-1.73-4.39-6-7.5-11-7.5-1.4 0-2.74.25-3.98.7l2.16 2.16C10.74 7.13 11.35 7 12 7zM2 4.27l2.28 2.28.46.46C3.08 8.3 1.78 10.02 1 12c1.73 4.39 6 7.5 11 7.5 1.55 0 3.03-.3 4.38-.84l.42.42L19.73 22 21 20.73 3.27 3 2 4.27zM7.53 9.8l1.55 1.55c-.05.21-.08.43-.08.65 0 1.66 1.34 3 3 3 .22 0 .44-.03.65-.08l1.55 1.55c-.67.33-1.41.53-2.2.53-2.76 0-5-2.24-5-5 0-.79.2-1.53.53-2.2zm4.31-.78 3.15 3.15.02-.16c0-1.66-1.34-3-3-3l-.17.01z"
      />
    </svg>
  );
}

/**
 * Full-screen login gate (login card ported from NAS4USB's LoginDialog).
 * Shown whenever there is no valid session.
 */
export default function LoginScreen() {
  const appInfo = useAppInfo();
  const { login, loggingIn, error, clearError } = useAuth();
  const [id, setId] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [showDefaultAdminHint, setShowDefaultAdminHint] = useState(false);
  const idInputRef = useRef(/** @type {HTMLInputElement | null} */ (null));

  useEffect(() => {
    let cancelled = false;
    void api('auth.hint')
      .then((hint) => {
        if (!cancelled) setShowDefaultAdminHint(Boolean(hint?.showDefaultAdminHint));
      })
      .catch(() => undefined);
    idInputRef.current?.focus({ preventScroll: true });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = (event) => {
    event.preventDefault();
    clearError();
    void login(id.trim(), password, rememberMe).then((ok) => {
      if (!ok) setPassword('');
    });
  };

  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-6 bg-[#0a1a33] p-4">
      <div className="flex items-center gap-[18px]">
        <AppLogo size={56} className="rounded-[14px] bg-white" />
        <div className="flex flex-col gap-1">
          <h1 className="m-0 text-[22px] font-bold leading-tight tracking-tight text-white">
            {appInfo.name}
          </h1>
          <p className="m-0 text-[11px] text-[#8fa0b8]">v{appInfo.version}</p>
        </div>
      </div>

      <form
        className="w-full max-w-[360px] rounded-xl bg-white p-6 shadow-lg"
        onSubmit={handleSubmit}
        aria-labelledby="login-title"
      >
        <h2 id="login-title" className="m-0 text-lg font-medium text-slate-900">
          로그인
        </h2>
        <p className="mt-1 text-sm text-slate-500">회원 계정으로 로그인한 뒤 이용합니다.</p>
        {showDefaultAdminHint ? (
          <p className="mt-2 text-xs leading-snug text-app-accentText">
            최초 로그인 ID / PWD : admin / admin1234 (변경 후 사용)
          </p>
        ) : null}

        <div className="mt-4 space-y-3">
          <label className="block text-sm text-slate-600">
            아이디
            <input
              ref={idInputRef}
              type="text"
              className={`${fieldClass} mt-1`}
              value={id}
              autoComplete="username"
              disabled={loggingIn}
              onChange={(event) => setId(event.target.value)}
            />
          </label>
          <label className="block text-sm text-slate-600">
            비밀번호
            <div className="relative mt-1">
              <input
                type={showPassword ? 'text' : 'password'}
                className={`${fieldClass} pr-10`}
                value={password}
                autoComplete="current-password"
                disabled={loggingIn}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button
                type="button"
                className="absolute right-1 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border-0 bg-transparent text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-60"
                aria-label={showPassword ? '비밀번호 숨기기' : '비밀번호 표시'}
                aria-pressed={showPassword}
                disabled={loggingIn}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setShowPassword((prev) => !prev)}
              >
                <PasswordVisibilityIcon visible={showPassword} />
              </button>
            </div>
          </label>
        </div>

        {error ? (
          <p className="mt-3 text-sm text-[#c5221f]" role="alert">
            {error}
          </p>
        ) : null}

        <div className="mt-5 flex items-center justify-between gap-3">
          <label className="inline-flex cursor-pointer select-none items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300 accent-app-accent"
              checked={rememberMe}
              disabled={loggingIn}
              onChange={(event) => setRememberMe(event.target.checked)}
            />
            로그인 유지
          </label>
          <button
            type="submit"
            className="rounded-full bg-app-accent px-5 py-2 text-sm font-medium text-white hover:bg-app-accentHover disabled:opacity-60"
            disabled={loggingIn || !id.trim() || !password}
          >
            {loggingIn ? '로그인 중…' : '로그인'}
          </button>
        </div>
      </form>
    </div>
  );
}
