import { useState, useCallback } from 'react';

export interface UseRequestOptions<T> {
  manual?: boolean;
  defaultParams?: unknown[];
  onSuccess?: (data: T) => void;
  onError?: (err: Error) => void;
}

export function useRequest<T, P extends unknown[] = unknown[]>(
  serviceFn: (...params: P) => Promise<T>,
  options: UseRequestOptions<T> = {},
) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | undefined>(undefined);

  const run = useCallback(
    async (...params: P) => {
      setLoading(true);
      setError(undefined);
      try {
        const result = await serviceFn(...params);
        setData(result);
        options.onSuccess?.(result);
        return result;
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        setError(e);
        options.onError?.(e);
        throw e;
      } finally {
        setLoading(false);
      }
    },
    [serviceFn, options],
  );

  const mutate = useCallback(
    (newData: T | ((prev: T | undefined) => T)) => {
      setData((prev) => {
        if (typeof newData === 'function') {
          return (newData as (prev: T | undefined) => T)(prev) as T;
        }
        return newData;
      });
    },
    [],
  );

  return { data, loading, error, run, mutate };
}
