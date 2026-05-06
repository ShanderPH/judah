"use client";

import { Alert, Button, Input, Label, TextField } from "@heroui/react";
import gsap from "gsap";
import { ArrowRight, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { authClient, ApiClientError } from "@/src/lib/api/client";
import { LoginCarousel } from "@/src/features/auth/login-carousel";

export function LoginForm({
  nextPath = "/dashboard",
}: {
  nextPath?: string;
}) {
  const router = useRouter();
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);
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
      setError("Preencha email e senha para continuar.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await authClient.login({ identity, password });
      router.replace(nextPath);
    } catch (cause) {
      if (cause instanceof ApiClientError) setError(cause.detail);
      else setError("Nao foi possivel iniciar a sessao no backend Judah.");
    } finally {
      setIsSubmitting(false);
    }
  };

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
            Backend autentica via{" "}
            <span className="judah-mono rounded-md bg-[var(--surface-tertiary)] px-1.5 py-0.5 text-xs">
              username + password
            </span>
            . Use seu email cadastrado.
          </p>
        </header>

        <form
          className="relative mt-7 flex flex-col gap-4"
          onSubmit={handleSubmit}
        >
          {error ? (
            <Alert status="danger" className="rounded-[var(--radius-md)]">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Title>Acesso negado</Alert.Title>
                <Alert.Description>{error}</Alert.Description>
              </Alert.Content>
            </Alert>
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
