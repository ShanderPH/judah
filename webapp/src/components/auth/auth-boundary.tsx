"use client";

import { Button, Card, Spinner } from "@heroui/react";
import { startTransition, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { authClient, ApiClientError } from "@/src/lib/api/client";
import { SessionProvider } from "@/src/lib/auth/session-context";
import type { User } from "@/src/types/api";

interface AuthState {
  error: Error | null;
  isLoading: boolean;
  user: User | null;
}

export function AuthBoundary({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const [state, setState] = useState<AuthState>({
    error: null,
    isLoading: true,
    user: null,
  });

  const loadSession = useCallback(async () => {
    startTransition(() => {
      setState((current) => ({ ...current, error: null, isLoading: true }));
    });

    try {
      const session = await authClient.session();
      startTransition(() => {
        setState({ error: null, isLoading: false, user: session.user });
      });
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 401) {
        router.replace(`/login?next=${encodeURIComponent(pathname)}`);
        return;
      }
      startTransition(() => {
        setState({
          error:
            error instanceof Error
              ? error
              : new Error("Nao foi possivel validar a sessao."),
          isLoading: false,
          user: null,
        });
      });
    }
  }, [pathname, router]);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  const signOut = async () => {
    await authClient.logout();
    router.replace("/login");
  };

  if (state.isLoading) {
    return (
      <div className="relative z-10 grid min-h-svh place-items-center px-4">
        <Card
          variant="default"
          className="judah-glass flex w-full max-w-sm flex-col items-center gap-4 rounded-[var(--radius-xl)] p-10 text-center"
        >
          <Spinner color="accent" size="lg" />
          <div className="space-y-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.3em] text-[var(--muted)]">
              Judah Session
            </p>
            <h1 className="text-xl font-semibold tracking-tight">
              Validando acesso
            </h1>
          </div>
        </Card>
      </div>
    );
  }

  if (!state.user) {
    return null;
  }

  if (state.error) {
    return (
      <div className="relative z-10 grid min-h-svh place-items-center px-4">
        <Card
          variant="default"
          className="judah-glass flex w-full max-w-xl flex-col gap-5 rounded-[var(--radius-xl)] p-8"
        >
          <div className="space-y-2">
            <p className="judah-mono text-[10px] uppercase tracking-[0.3em] text-[var(--danger)]">
              Falha de Sessao
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">
              Nao foi possivel carregar o painel.
            </h1>
            <p className="text-sm text-[var(--muted)]">{state.error.message}</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button onPress={() => void loadSession()}>Tentar novamente</Button>
            <Button variant="secondary" onPress={() => void signOut()}>
              Sair
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <SessionProvider
      value={{
        user: state.user,
        refreshSession: async () => {
          await loadSession();
        },
        signOut,
      }}
    >
      {children}
    </SessionProvider>
  );
}
