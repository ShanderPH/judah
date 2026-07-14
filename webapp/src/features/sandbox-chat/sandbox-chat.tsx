"use client";

import { useEffect, useRef, useState } from "react";

interface SandboxUser {
  email: string;
  firstName: string;
  id: number;
  lastName: string;
}

interface SandboxChatProps {
  portalId: string;
  user: SandboxUser;
}

interface VisitorTokenPayload {
  expiresAt: string;
  token: string;
}

interface HubSpotWidget {
  load: (options?: { widgetOpen?: boolean }) => void;
  remove: () => void;
}

declare global {
  interface Window {
    HubSpotConversations?: { widget: HubSpotWidget };
    _hsq?: unknown[];
    hsConversationsOnReady?: Array<() => void>;
    hsConversationsSettings?: {
      identificationEmail?: string;
      identificationToken?: string;
      inlineEmbedSelector?: string;
      loadImmediately?: boolean;
    };
  }
}

const scriptId = "hubspot-sandbox-chat-script";

/** Renders HubSpot's official web chat widget only on the sandbox test route. */
export function SandboxChat({ portalId, user }: SandboxChatProps) {
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Autenticando visitante no HubSpot…");
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    const configureWidget = (token: VisitorTokenPayload) => {
      window._hsq = window._hsq ?? [];
      window._hsq.push([
        "identify",
        {
          email: user.email,
          firstname: user.firstName,
          lastname: user.lastName,
        },
      ]);
      window._hsq.push(["trackPageView"]);

      window.hsConversationsSettings = {
        loadImmediately: false,
        inlineEmbedSelector: "#hubspot-sandbox-chat",
        identificationEmail: user.email,
        identificationToken: token.token,
      };

      const loadWidget = () => {
        window.HubSpotConversations?.widget.load({ widgetOpen: true });
        if (mountedRef.current) {
          setStatus("Chat conectado à sandbox");
        }
      };

      if (window.HubSpotConversations) {
        loadWidget();
        return;
      }

      window.hsConversationsOnReady = [...(window.hsConversationsOnReady ?? []), loadWidget];
      const existingScript = document.getElementById(scriptId);
      if (existingScript) {
        return;
      }

      const script = document.createElement("script");
      script.id = scriptId;
      script.async = true;
      script.defer = true;
      script.src = `https://js.hs-scripts.com/${portalId}.js`;
      script.onerror = () => {
        if (mountedRef.current) {
          setError("Nao foi possivel carregar o widget do HubSpot.");
        }
      };
      document.head.appendChild(script);
    };

    const initialise = async () => {
      try {
        const response = await fetch("/api/hubspot/visitor-token", { method: "POST" });
        const payload = (await response.json()) as VisitorTokenPayload | { detail?: string };

        if (!response.ok || !("token" in payload)) {
          throw new Error("detail" in payload ? payload.detail : "Falha ao autenticar o chat.");
        }

        configureWidget(payload);
      } catch (cause) {
        if (mountedRef.current) {
          setError(cause instanceof Error ? cause.message : "Falha ao iniciar o chat.");
          setStatus("Chat indisponivel");
        }
      }
    };

    void initialise();

    return () => {
      mountedRef.current = false;
      window.HubSpotConversations?.widget.remove();
    };
  }, [portalId, user.email, user.firstName, user.lastName]);

  return (
    <main className="relative z-10 flex min-h-svh items-center justify-center px-4 py-10">
      <section className="w-full max-w-2xl rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--surface-shadow)] sm:p-9">
        <p className="judah-mono text-[10px] uppercase tracking-[0.28em] text-[var(--muted)]">
          HubSpot sandbox · portal {portalId}
        </p>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">Chat de teste</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Sessão Judah autenticada como {user.email}. As mensagens desta página são enviadas somente ao chatflow
          configurado na sandbox HubSpot.
        </p>
        <p className="mt-5 text-xs font-medium text-[var(--accent-foreground)]" role="status">
          {status}
        </p>
        {error ? (
          <p className="mt-3 rounded-[var(--radius-sm)] bg-red-500/10 px-3 py-2 text-sm text-[var(--danger)]" role="alert">
            {error}
          </p>
        ) : null}
        <div id="hubspot-sandbox-chat" className="mt-6 min-h-[520px] overflow-hidden rounded-[var(--radius-md)]" />
      </section>
    </main>
  );
}
