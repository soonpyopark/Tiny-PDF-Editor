import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { UNAUTHORIZED_EVENT, api, clearToken, getToken, setToken } from '../lib/apiClient.js';

/**
 * @typedef {{
 *   status: 'loading' | 'anonymous' | 'authenticated',
 *   user: import('../../electron/authService.js').SessionUser | null,
 *   clientIp: string,
 *   isSuperAdmin: boolean,
 *   loggingIn: boolean,
 *   error: string,
 *   login: (id: string, password: string, remember: boolean) => Promise<boolean>,
 *   logout: () => Promise<void>,
 *   clearError: () => void,
 * }} AuthContextValue
 */

const AuthContext = createContext(/** @type {AuthContextValue | null} */ (null));

export function AuthProvider({ children }) {
  const [status, setStatus] = useState(/** @type {'loading' | 'anonymous' | 'authenticated'} */ ('loading'));
  const [user, setUser] = useState(null);
  const [clientIp, setClientIp] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);
  const [error, setError] = useState('');

  const reset = useCallback(() => {
    clearToken();
    setUser(null);
    setStatus('anonymous');
  }, []);

  // Restore a stored session on startup.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!getToken()) {
        setStatus('anonymous');
        return;
      }
      try {
        const me = await api('auth.me');
        if (cancelled) return;
        setUser(me.user);
        setClientIp(me.clientIp);
        setStatus('authenticated');
      } catch {
        if (!cancelled) reset();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reset]);

  // Any API call that comes back 401 (expired / revoked session) drops to the login screen.
  useEffect(() => {
    const onUnauthorized = () => reset();
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [reset]);

  const login = useCallback(async (id, password, remember) => {
    setLoggingIn(true);
    setError('');
    try {
      const result = await api('auth.login', { id, password, remember });
      setToken(result.token, remember);
      setUser(result.user);
      setClientIp(result.clientIp);
      setStatus('authenticated');
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '로그인에 실패했습니다.');
      return false;
    } finally {
      setLoggingIn(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api('auth.logout');
    } catch {
      // the local session is dropped either way
    }
    reset();
  }, [reset]);

  const clearError = useCallback(() => setError(''), []);

  const value = useMemo(
    () => ({
      status,
      user,
      clientIp,
      isSuperAdmin: user?.role === 'super_admin',
      loggingIn,
      error,
      login,
      logout,
      clearError,
    }),
    [status, user, clientIp, loggingIn, error, login, logout, clearError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}
