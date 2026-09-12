import { useCallback, useEffect, useRef, useState } from 'react';

export function useData<T>(fn: () => T, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    let live = true;
    const run = () => {
      try {
        const d = fnRef.current();
        if (live) {
          setData(d);
          setError('');
        }
      } catch (e) {
        if (live) setError(String((e as Error).message || e));
      }
    };
    run();
    if (pollMs && pollMs > 0) {
      const t = setInterval(run, pollMs);
      return () => {
        live = false;
        clearInterval(t);
      };
    }
    return () => {
      live = false;
    };
  }, [tick, pollMs]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, reload };
}
