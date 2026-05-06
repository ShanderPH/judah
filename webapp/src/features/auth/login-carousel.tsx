"use client";

import gsap from "gsap";
import { Activity, Layers, Sparkles, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface Slide {
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  palette: { from: string; via: string; to: string };
}

const slides: Slide[] = [
  {
    eyebrow: "01 — Operacao",
    title: "Controle operacional em tempo real.",
    description:
      "JWT seguro em cookies HttpOnly. Leitura direta do backend Judah, sem proxy paralelo.",
    icon: Sparkles,
    palette: { from: "#90be42", via: "#b6dd7e", to: "#f9e813" },
  },
  {
    eyebrow: "02 — Fila",
    title: "Fila inteligente sem improviso.",
    description:
      "Pendentes, atribuicoes e saude da distribuicao em uma unica camada observavel.",
    icon: Layers,
    palette: { from: "#75a132", via: "#90be42", to: "#6eda2c" },
  },
  {
    eyebrow: "03 — Metricas",
    title: "Metricas reais, publicadas pelo backend.",
    description:
      "Relatorios diarios, series da fila e SLA sem inventar APIs.",
    icon: Activity,
    palette: { from: "#f9e813", via: "#90be42", to: "#0693e3" },
  },
];

export function LoginCarousel() {
  const [active, setActive] = useState(0);
  const slidesRef = useRef<HTMLDivElement | null>(null);
  const phrasesRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => {
      setActive((current) => (current + 1) % slides.length);
    }, 6500);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!slidesRef.current) return;
    const ctx = gsap.context(() => {
      gsap.to("[data-slide]", {
        autoAlpha: 0,
        duration: 0.8,
        ease: "power2.out",
      });
      gsap.to(`[data-slide="${active}"]`, {
        autoAlpha: 1,
        duration: 1.2,
        ease: "power3.out",
      });
    }, slidesRef);
    return () => ctx.revert();
  }, [active]);

  useEffect(() => {
    if (!phrasesRef.current) return;
    const ctx = gsap.context(() => {
      gsap.from("[data-phrase-block]", {
        autoAlpha: 0,
        y: 22,
        duration: 0.7,
        stagger: 0.1,
        ease: "power3.out",
        clearProps: "all",
      });
    }, phrasesRef);
    const safety = window.setTimeout(() => {
      gsap.set("[data-phrase-block]", { autoAlpha: 1, y: 0, clearProps: "all" });
    }, 1500);
    return () => {
      window.clearTimeout(safety);
      ctx.revert();
    };
  }, [active]);

  const current = slides[active];
  const Icon = current.icon;

  return (
    <div className="judah-glass-strong relative isolate flex h-full min-h-[460px] flex-col justify-between overflow-hidden rounded-[var(--radius-xl)] p-6 md:p-10">
      <div ref={slidesRef} className="absolute inset-0 -z-10">
        {slides.map((slide, idx) => (
          <div
            key={slide.eyebrow}
            data-slide={idx}
            style={{ opacity: idx === active ? 1 : 0 }}
            className="absolute inset-0"
          >
            <div
              className="absolute inset-0 animate-carousel-pan"
              style={{
                background: `radial-gradient(ellipse 70% 60% at 18% 24%, ${slide.palette.from}38, transparent 65%), radial-gradient(ellipse 55% 50% at 82% 70%, ${slide.palette.to}3a, transparent 65%), linear-gradient(135deg, ${slide.palette.from}1a, ${slide.palette.via}1f 50%, ${slide.palette.to}1c)`,
              }}
            />
            <svg
              aria-hidden
              viewBox="0 0 600 800"
              preserveAspectRatio="xMidYMid slice"
              className="absolute inset-0 h-full w-full opacity-70 mix-blend-overlay"
            >
              <defs>
                <radialGradient id={`grad-${idx}`} cx="50%" cy="50%" r="60%">
                  <stop offset="0%" stopColor={slide.palette.from} stopOpacity="0.7" />
                  <stop offset="100%" stopColor={slide.palette.to} stopOpacity="0" />
                </radialGradient>
                <linearGradient id={`stroke-${idx}`} x1="0" x2="1" y1="0" y2="1">
                  <stop offset="0%" stopColor={slide.palette.from} stopOpacity="0.9" />
                  <stop offset="100%" stopColor={slide.palette.to} stopOpacity="0.3" />
                </linearGradient>
              </defs>
              <circle cx="120" cy="180" r="180" fill={`url(#grad-${idx})`} />
              <circle cx="480" cy="620" r="220" fill={`url(#grad-${idx})`} />
              <g
                fill="none"
                stroke={`url(#stroke-${idx})`}
                strokeWidth="1"
                opacity="0.55"
              >
                <path d="M-50 200 Q 200 120 400 260 T 700 380" />
                <path d="M-50 360 Q 200 280 400 420 T 700 540" />
                <path d="M-50 520 Q 200 440 400 580 T 700 700" />
              </g>
              <g
                fill={slide.palette.via}
                opacity="0.45"
                style={{ mixBlendMode: "screen" }}
              >
                <circle cx="80" cy="540" r="3" />
                <circle cx="200" cy="220" r="2" />
                <circle cx="340" cy="380" r="2.5" />
                <circle cx="500" cy="160" r="3" />
                <circle cx="430" cy="500" r="2" />
                <circle cx="260" cy="660" r="2.5" />
              </g>
            </svg>
          </div>
        ))}
        <div
          aria-hidden
          className="judah-blob judah-blob--brand absolute -top-24 -left-24 h-80 w-80 animate-drift-1"
        />
        <div
          aria-hidden
          className="judah-blob judah-blob--accent absolute -bottom-32 -right-16 h-96 w-96 animate-drift-2"
        />
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.5) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />
      </div>

      <header className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-2xl bg-[var(--surface)]/80 text-[var(--accent)] shadow-[var(--field-shadow)] backdrop-blur">
            <Sparkles className="size-4" strokeWidth={2.2} />
          </span>
          <div className="leading-tight">
            <p className="judah-mono text-[10px] uppercase tracking-[0.32em] text-[var(--muted)]">
              Judah
            </p>
            <p className="judah-display text-base">Command Grid</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {slides.map((slide, idx) => (
            <button
              key={slide.eyebrow}
              type="button"
              onClick={() => setActive(idx)}
              aria-label={`Slide ${idx + 1}`}
              className="judah-focus-ring h-1.5 rounded-full bg-[var(--ink-300)] transition-all duration-500"
              style={{
                width: idx === active ? 28 : 10,
                background:
                  idx === active ? "var(--accent)" : "color-mix(in srgb, var(--ink-300) 80%, transparent)",
              }}
            />
          ))}
        </div>
      </header>

      <div ref={phrasesRef} key={active} className="relative max-w-2xl space-y-5">
        <div data-phrase-block className="flex items-center gap-3">
          <span className="grid size-12 place-items-center rounded-2xl bg-[var(--surface)]/80 text-[var(--accent)] shadow-[var(--shadow-glow)] backdrop-blur">
            <Icon className="size-5" strokeWidth={1.8} />
          </span>
          <span className="judah-chip">{current.eyebrow}</span>
        </div>
        <h2
          data-phrase-block
          className="judah-display text-balance text-4xl leading-[1.05] tracking-tight md:text-5xl lg:text-[3.4rem]"
        >
          {current.title}
        </h2>
        <p
          data-phrase-block
          className="text-pretty text-base leading-relaxed text-[var(--ink-700)] md:text-lg"
        >
          {current.description}
        </p>
      </div>

      <footer className="relative grid grid-cols-3 gap-3 text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">
        <Stat label="Sessao" value="HttpOnly" />
        <Stat label="Fila" value="Live" />
        <Stat label="Metricas" value="Daily" />
      </footer>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="judah-glass rounded-2xl px-3 py-2.5">
      <p className="judah-mono text-[9px] tracking-[0.22em]">{label}</p>
      <p className="judah-display mt-1 text-sm normal-case tracking-normal text-[var(--foreground)]">
        {value}
      </p>
    </div>
  );
}
