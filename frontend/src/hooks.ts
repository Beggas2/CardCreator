import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export function usePoll<T>(url: string | null, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    if (!url) return;
    try {
      setData(await api.get<T>(url));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [url]);
  useEffect(() => setData(null), [url]); // dados de outra URL nunca aparecem como se fossem desta
  useEffect(() => {
    reload();
    if (!intervalMs) return;
    const id = setInterval(reload, intervalMs);
    return () => clearInterval(id);
  }, [reload, intervalMs]);
  return { data, error, reload };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run, setError };
}
