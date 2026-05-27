/**
 * usePolling — polls a fetcher function on an interval.
 * DA-5: 30s default refresh for dashboard endpoints.
 */
import { useEffect, useRef, useState, useCallback } from "react";

interface UsePollingOptions {
  interval?: number;  // ms; default 30000
  enabled?: boolean;
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  options: UsePollingOptions = {},
) {
  const { interval = 30_000, enabled = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const fetch = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    fetch();
    const id = setInterval(fetch, interval);
    return () => clearInterval(id);
  }, [enabled, interval, fetch]);

  return { data, loading, error, refetch: fetch };
}
