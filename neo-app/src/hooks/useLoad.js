import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Loads data on mount and on demand.
 *
 * @template T
 * @param {() => Promise<T>} loader
 * @returns {{ data: T | null, loading: boolean, error: string, reload: () => Promise<void>, setData: (value: T) => void }}
 */
export function useLoad(loader) {
  const [data, setData] = useState(/** @type {T | null} */ (null));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const aliveRef = useRef(true);

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const next = await loaderRef.current();
      if (aliveRef.current) setData(next);
    } catch (err) {
      if (aliveRef.current) setError(err instanceof Error ? err.message : '불러오지 못했습니다.');
    } finally {
      if (aliveRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    void reload();
    return () => {
      aliveRef.current = false;
    };
  }, [reload]);

  return { data, loading, error, reload, setData };
}
