"use client";

import { Button, Card } from "@heroui/react";
import {
  Activity,
  BarChart3,
  Gauge,
  Menu,
  Orbit,
  PanelLeftClose,
  Sparkles,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";


import { useSession } from "@/src/lib/auth/session-context";
import { CAPABILITIES, hasCapability, type Capability } from "@/src/lib/auth/access-policy";
import { cn } from "@/src/lib/utils/misc";
import { StatusRail } from "@/src/components/layout/status-rail";
import { ThemeToggle } from "@/src/components/layout/theme-toggle";
import { PageTransition } from "@/src/lib/motion/page-transition";
import { gsap, MOTION, useGSAP } from "@/src/lib/motion/use-gsap";

const navigation: ReadonlyArray<{ href: string; icon: typeof Gauge; label: string; hint: string; capability: Capability }> = [
  { href: "/dashboard", icon: Gauge, label: "Dashboard", hint: "Visao geral", capability: CAPABILITIES.dashboardRead },
  { href: "/queue", icon: Orbit, label: "Fila", hint: "Operacao em tempo real", capability: CAPABILITIES.supportAdminRead },
  { href: "/auto-assignment", icon: Activity, label: "Autoatribuicao", hint: "Distribuicao", capability: CAPABILITIES.supportAdminRead },
  { href: "/agents", icon: Users, label: "Agentes", hint: "Gestao da equipe", capability: CAPABILITIES.supportAdminRead },
  { href: "/metrics", icon: BarChart3, label: "Metricas", hint: "Analytics", capability: CAPABILITIES.metricsRead },
];

function Sidebar({
  isMobileOpen,
  onClose,
}: {
  isMobileOpen: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();
  const { user } = useSession();
  const ref = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!isMobileOpen) return;

    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [isMobileOpen, onClose]);

  useGSAP(
    () => {
      const media = gsap.matchMedia();
      media.add(
        {
          allowMotion: "(prefers-reduced-motion: no-preference)",
          desktop: "(min-width: 1024px)",
        },
        (context) => {
          if (!context.conditions?.allowMotion || !context.conditions.desktop) return;
          gsap.from("[data-side-item], nav > a", {
            autoAlpha: 0,
            x: -14,
            duration: MOTION.duration.base,
            stagger: 0.045,
            ease: MOTION.ease.enter,
            clearProps: "transform,opacity,visibility,willChange",
          });
        },
      );
      return () => media.revert();
    },
    { scope: ref },
  );

  return (
    <>
      <aside
        ref={ref}
        aria-label="Navegacao principal"
        className={cn(
          "judah-glass judah-scroll fixed inset-y-3 left-3 z-40 flex w-[280px] flex-col gap-6 overflow-y-auto rounded-[var(--radius-xl)] p-5 transition-transform duration-300 lg:sticky lg:top-3 lg:left-0 lg:max-h-[calc(100svh-1.5rem)] lg:translate-x-0",
          isMobileOpen
            ? "visible translate-x-0"
            : "invisible -translate-x-[110%] lg:visible lg:translate-x-0",
        )}
      >
        <div data-side-item className="space-y-3">
          <div className="flex items-center justify-between">
            <Link href="/dashboard" prefetch={false} className="flex items-center gap-2.5">
              <span className="grid size-9 place-items-center rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--brand-700)] text-[var(--accent-foreground)] shadow-[var(--field-shadow)]">
                <Sparkles className="size-4" strokeWidth={2.2} />
              </span>
              <div className="leading-tight">
                <p className="text-[10px] uppercase tracking-[0.32em] text-[var(--muted)]">
                  Judah
                </p>
                <h1 className="text-base font-semibold">Command Grid</h1>
              </div>
            </Link>
            <Button
              ref={closeButtonRef}
              isIconOnly
              variant="ghost"
              className="lg:hidden"
              onPress={onClose}
              aria-label="Fechar menu"
            >
              <PanelLeftClose className="size-4" />
            </Button>
          </div>
          <p className="text-sm leading-relaxed text-[var(--muted)]">
            Operacao centralizada com sessoes protegidas e leitura direta do backend.
          </p>
        </div>

        <Card
          variant="secondary"
                    className="rounded-[var(--radius-lg)] p-4"
        >
          <div className="flex items-center justify-between">
            <span className="judah-mono text-[10px] uppercase tracking-[0.26em] text-[var(--muted)]">
              Acesso
            </span>
            <span className="judah-mono rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-[var(--accent)]">
              {user.role}
            </span>
          </div>
          <div className="mt-2">
            <p className="text-base font-semibold leading-tight">
              {user.first_name || user.username}
            </p>
            <p className="truncate text-xs text-[var(--muted)]">{user.email}</p>
          </div>
        </Card>

        <nav className="flex flex-col gap-1.5">
          {navigation.filter((item) => hasCapability(user, item.capability)).map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                prefetch={false}
                                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "judah-focus-ring group relative flex items-center gap-3 rounded-[var(--radius-md)] border px-3 py-3 text-sm transition-all duration-300",
                  isActive
                    ? "border-[var(--accent)]/40 bg-[var(--surface-tertiary)] shadow-[var(--surface-shadow)]"
                    : "border-transparent hover:border-[var(--border)] hover:bg-[var(--surface-secondary)]",
                )}
                onClick={onClose}
              >
                {isActive ? (
                  <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-[var(--accent)]" />
                ) : null}
                <span
                  className={cn(
                    "grid size-9 place-items-center rounded-xl border transition-all duration-300",
                    isActive
                      ? "border-[var(--accent)]/30 bg-[var(--accent)]/10 text-[var(--accent)]"
                      : "border-[var(--border)] bg-[var(--surface)] text-[var(--foreground)] group-hover:border-[var(--accent)]/30 group-hover:text-[var(--accent)]",
                  )}
                >
                  <Icon className="size-4" strokeWidth={1.8} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium leading-none">{item.label}</p>
                  <p className="judah-mono mt-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--muted)]">
                    {isActive ? "Em foco" : item.hint}
                  </p>
                </div>
              </Link>
            );
          })}
        </nav>

        <div data-side-item className="mt-auto">
          <div className="judah-divider mb-4" />
          <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
            v0.1.0 • sessao protegida
          </p>
        </div>
      </aside>

      {isMobileOpen ? (
        <button
          type="button"
          aria-label="Fechar menu"
          className="fixed inset-0 z-30 bg-[var(--backdrop)] backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      ) : null}
    </>
  );
}

function TopBar({
  menuButtonRef,
  onMenuOpen,
}: {
  menuButtonRef: React.RefObject<HTMLButtonElement | null>;
  onMenuOpen: () => void;
}) {
  const { signOut, user } = useSession();
  const pathname = usePathname();
  const current = navigation.find((item) => item.href === pathname);

  return (
    <div className="judah-glass sticky top-3 z-20 mb-4 flex items-center justify-between gap-3 rounded-[var(--radius-lg)] px-4 py-3 md:px-5">
      <div className="flex min-w-0 items-center gap-3">
        <Button
          ref={menuButtonRef}
          isIconOnly
          variant="tertiary"
          className="lg:hidden"
          onPress={onMenuOpen}
          aria-label="Abrir menu"
        >
          <Menu className="size-4" />
        </Button>
        <div className="min-w-0">
          <p className="judah-mono text-[10px] uppercase tracking-[0.3em] text-[var(--muted)]">
            {current?.hint ?? "Operacoes"}
          </p>
          <h2 className="truncate text-lg font-semibold leading-tight md:text-xl">
            {current?.label ?? "Operacoes"}
          </h2>
        </div>
      </div>

      <div className="flex items-center gap-2 md:gap-3">
        <div className="hidden text-right md:block">
          <p className="text-sm font-medium leading-tight">{user.username}</p>
          <p className="judah-mono text-[10px] uppercase tracking-[0.22em] text-[var(--muted)]">
            {user.role}
          </p>
        </div>
        <ThemeToggle />
        <Button variant="secondary" size="sm" onPress={() => void signOut()}>
          Sair
        </Button>
      </div>
    </div>
  );
}

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const closeMobile = useCallback(() => {
    setIsMobileOpen(false);
    window.requestAnimationFrame(() => menuButtonRef.current?.focus());
  }, []);
  const openMobile = useCallback(() => setIsMobileOpen(true), []);

  return (
    <div className="relative z-10 min-h-svh px-3 pb-6 pt-3 md:px-4 md:pb-8 md:pt-4">
      <div className="mx-auto grid w-full max-w-[1680px] gap-3 md:gap-4 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)_320px]">
        <Sidebar
          isMobileOpen={isMobileOpen}
          onClose={closeMobile}
        />

        <main className="min-w-0">
          <TopBar menuButtonRef={menuButtonRef} onMenuOpen={openMobile} />
          <PageTransition>
            <div className="space-y-4 md:space-y-5">{children}</div>
          </PageTransition>
        </main>

        <StatusRail />
      </div>
    </div>
  );
}
