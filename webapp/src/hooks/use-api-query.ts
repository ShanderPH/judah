"use client";

import {
  startTransition,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { ApiClientError } from "@/src/lib/api/client";

interface QueryState<T> {
  data: T | null;
  error: Error | null;
  isLoading: boolean;
  isRefreshing: boolean;
}

export function useApiQuery<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  initialData: T | null = null,
): QueryState<T> & {
  reload: () => Promise<void>;
} {
  const [state, setState] = useState<QueryState<T>>({
    data: initialData,
    error: null,
    isLoading: initialData === null,
    isRefreshing: false,
  });
  const controllerRef = useRef<AbortController | null>(null);
  const hasInitialData = useRef(initialData !== null);

  const run = useCallback(async (isRefresh: boolean) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    startTransition(() => {
      setState((current) => ({
        ...current,
        error: null,
        isLoading: current.data === null && !isRefresh,
        isRefreshing: current.data !== null || isRefresh,
      }));
    });

    try {
      const data = await fetcher(controller.signal);
      if (controller.signal.aborted) return;
      startTransition(() => {
        setState({
          data,
          error: null,
          isLoading: false,
          isRefreshing: false,
        });
      });
    } catch (error) {
      if (controller.signal.aborted) return;
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
    if (hasInitialData.current) {
      hasInitialData.current = false;
      return () => controllerRef.current?.abort();
    }
    void run(false);
    return () => controllerRef.current?.abort();
  }, [run]);

  return {
    ...state,
    reload: () => run(true),
  };
}
