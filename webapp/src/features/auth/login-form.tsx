"use client";

import { Alert, Button, CloseButton, Input, Label, TextField } from "@heroui/react";
import gsap from "gsap";
import { ArrowRight, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { authClient, ApiClientError } from "@/src/lib/api/client";
import { LoginCarousel } from "@/src/features/auth/login-carousel";

interface LoginErrorView {
  title: string;
  description: string;
}

const KNOWN_BACKEND_MESSAGES: Record<string, LoginErrorView> = {
  "Invalid username or password.": {
    title: "Credenciais invalidas",
    description: "Email ou senha incorretos. Verifique e tente novamente.",
  },
  "This account has been deactivated.": {
    title: "Conta desativada",
    description: "Esta conta foi desativada. Contate um administrador para reativar.",
  },
  "Authentication is temporarily unavailable.": {
    title: "Servico de autenticacao indisponivel",
    description: "O backend nao conseguiu validar credenciais agora. Tente novamente em instantes.",
  },
  "Authentication subsystem is temporarily unavailable.": {
    title: "Servico de autenticacao indisponivel",
    description: "O backend autenticou, mas falhou ao emitir o token. Tente novamente em instantes.",
  },
};

function describeLoginFailure(cause: unknown): LoginErrorView {
  if (cause instanceof ApiClientError) {
    const known = KNOWN_BACKEND_MESSAGES[cause.detail];
    if (known) return known;

    if (cause.status === 401 || cause.status === 403) {
      return {
        title: "Credenciais invalidas",
        description: cause.detail || "Email ou senha incorretos.",
      };
    }
    if (cause.status === 422 || cause.status === 400) {
      return {
        title: "Dados invalidos",
        description: cause.detail || "Revise os campos e tente novamente.",
      };
    }
    if (cause.status === 502 || cause.status === 503 || cause.status === 504) {
      return {
        title: "Servico de autenticacao indisponivel",
        description:
          cause.detail || "Nao foi possivel contatar o backend Judah. Tente novamente em instantes.",
      };
    }
    return {
      title: "Falha ao autenticar",
      description: cause.detail || "Erro inesperado durante o login.",
    };
  }
  return {
    title: "Falha de rede",
    description: "Nao foi possivel iniciar a sessao. Verifique sua conexao e tente novamente.",
  };
}

export function LoginForm({
  nextPath = "/dashboard",
}: {
  nextPath?: string;
}) {
  const router = useRouter();
  const cardRef = useRef<HTMLDivElement | null>(null);
  const alertRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<LoginErrorView | null>(null);
  const [identity, setIdentity] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!cardRef.current) return;
    const targets =
      "[data-card-eyebrow],[data-card-title],[data-card-desc],[data-card-field],[data-card-action],[data-card-foot]";
    const ctx = gsap.context(() => {
      gsap.from(targets, {
        autoAlpha: 0,
        y: 18,
        duration: 0.6,
        ease: "power3.out",
        stagger: 0.08,
        clearProps: "all",
      });
    }, cardRef);
    const safety = window.setTimeout(() => {
      gsap.set(targets, { autoAlpha: 1, y: 0, clearProps: "all" });
    }, 1500);
    return () => {
      window.clearTimeout(safety);
      ctx.revert();
    };
  }, []);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!identity.trim() || !password) {
      setError({
        title: "Campos obrigatorios",
        description: "Preencha email e senha para continuar.",
      });
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await authClient.login({ identity, password });
      router.replace(nextPath);
    } catch (cause) {
      setError(describeLoginFailure(cause));
    } finally {
      setIsSubmitting(false);
    }
  };

  useEffect(() => {
    if (!error || !alertRef.current) return;
    alertRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    gsap.fromTo(
      alertRef.current,
      { autoAlpha: 0, y: -8, scale: 0.98 },
      { autoAlpha: 1, y: 0, scale: 1, duration: 0.32, ease: "power2.out" },
    );
  }, [error]);

  return (
    <div className="relative z-10 mx-auto grid min-h-svh w-full max-w-[1480px] gap-4 px-3 py-4 md:gap-6 md:px-6 md:py-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(420px,480px)] lg:items-stretch">
      <div className="lg:order-1">
        <LoginCarousel />
      </div>

      <div
        ref={cardRef}
        className="judah-glass-strong relative isolate flex flex-col justify-center overflow-hidden rounded-[var(--radius-xl)] p-6 md:p-10 lg:order-2"
      >
        <div
          aria-hidden
          className="judah-blob judah-blob--brand absolute -top-24 right-0 h-64 w-64 animate-drift-1"
        />
        <div
          aria-hidden
          className="judah-blob judah-blob--accent absolute -bottom-32 -left-16 h-72 w-72 animate-drift-2"
        />

        <header className="relative space-y-2">
          <span data-card-eyebrow className="judah-chip">
            <ShieldCheck className="size-3" />
            Autenticacao
          </span>
          <h1
            data-card-title
            className="judah-display text-balance text-3xl tracking-tight md:text-4xl"
          >
            Entrar no painel Judah
          </h1>
          <p
            data-card-desc
            className="text-pretty text-sm leading-relaxed text-[var(--ink-600)]"
          >
            Use seu{" "}
            <span className="judah-mono rounded-md bg-[var(--surface-tertiary)] px-1.5 py-0.5 text-xs">
              email
            </span>{" "}
            cadastrado e a senha do painel.
          </p>
        </header>

        <form
          className="relative mt-7 flex flex-col gap-4"
          onSubmit={handleSubmit}
        >
          {error ? (
            <div
              ref={alertRef}
              role="alert"
              aria-live="assertive"
              className="w-full"
            >
              <Alert
                status="danger"
                className="w-full rounded-[var(--radius-md)] shadow-sm sm:items-start"
              >
                <Alert.Indicator />
                <Alert.Content className="gap-1">
                  <Alert.Title className="text-sm font-semibold leading-tight sm:text-base">
                    {error.title}
                  </Alert.Title>
                  <Alert.Description className="text-xs leading-relaxed text-pretty sm:text-sm">
                    {error.description}
                  </Alert.Description>
                </Alert.Content>
                <CloseButton
                  aria-label="Fechar alerta"
                  onPress={() => setError(null)}
                />
              </Alert>
            </div>
          ) : null}

          <div data-card-field>
            <TextField
              name="identity"
              type="email"
              value={identity}
              onChange={setIdentity}
              isRequired
              fullWidth
            >
              <Label className="judah-mono text-[10px] font-semibold uppercase tracking-[0.24em] text-[var(--muted)]">
                Email
              </Label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-[var(--muted)]" />
                <Input
                  autoComplete="username"
                  placeholder="felipe@empresa.com"
                  variant="secondary"
                  className="pl-11"
                />
              </div>
            </TextField>
          </div>

          <div data-card-field>
            <TextField
              name="password"
              type="password"
              value={password}
              onChange={setPassword}
              isRequired
              fullWidth
            >
              <Label className="judah-mono text-[10px] font-semibold uppercase tracking-[0.24em] text-[var(--muted)]">
                Senha
              </Label>
              <div className="relative">
                <LockKeyhole className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-[var(--muted)]" />
                <Input
                  autoComplete="current-password"
                  placeholder="********"
                  variant="secondary"
                  className="pl-11"
                />
              </div>
            </TextField>
          </div>

          <div data-card-action className="pt-2">
            <Button
              type="submit"
              fullWidth
              size="lg"
              isPending={isSubmitting}
              className="group rounded-[var(--field-radius)]"
            >
              Acessar operacao
              <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-1" />
            </Button>
          </div>
        </form>

        <footer
          data-card-foot
          className="relative mt-6 flex items-center justify-between text-xs text-[var(--muted)]"
        >
          <span className="judah-mono uppercase tracking-[0.22em]">
            v0.1.0
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-1.5 rounded-full bg-[var(--success)]" />
            Backend live
          </span>
        </footer>
      </div>
    </div>
  );
}
