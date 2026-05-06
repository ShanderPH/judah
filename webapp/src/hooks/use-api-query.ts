"use client";

import {
  startTransition,
  useCallback,
  useEffect,
  useState,
} from "react";

import { ApiClientError } from "@/src/lib/api/client";

interface QueryState<T> {
  data: T | null;
  error: Error | null;
  isLoading: boolean;
  isRefreshing: boolean;
}

export function useApiQuery<T>(fetcher: () => Promise<T>): QueryState<T> & {
  reload: () => Promise<void>;
} {
  const [state, setState] = useState<QueryState<T>>({
    data: null,
    error: null,
    isLoading: true,
    isRefreshing: false,
  });
  const [reloadTick, setReloadTick] = useState(0);

  const run = useCallback(async (isRefresh: boolean) => {
    startTransition(() => {
      setState((current) => ({
        ...current,
        error: null,
        isLoading: current.data === null && !isRefresh,
        isRefreshing: current.data !== null || isRefresh,
      }));
    });

    try {
      const data = await fetcher();
      startTransition(() => {
        setState({
          data,
          error: null,
          isLoading: false,
          isRefreshing: false,
        });
      });
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 401 && typeof window !== "undefined") {
        window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
        return;
      }

      startTransition(() => {
        setState((current) => ({
          ...current,
          error: error instanceof Error ? error : new Error("Request failed."),
          isLoading: false,
          isRefreshing: false,
        }));
      });
    }
  }, [fetcher]);

  useEffect(() => {
    void run(reloadTick > 0);
  }, [reloadTick, run]);

  return {
    ...state,
    reload: async () => {
      setReloadTick((current) => current + 1);
    },
  };
}
