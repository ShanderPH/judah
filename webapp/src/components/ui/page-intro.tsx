"use client";

import gsap from "gsap";
import { useEffect, useRef } from "react";

interface PageIntroProps {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}

export function PageIntro({ eyebrow, title, description, action }: PageIntroProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!rootRef.current) return;
    const ctx = gsap.context(() => {
      gsap.from("[data-intro-item]", {
        autoAlpha: 0,
        y: 24,
        duration: 0.65,
        ease: "power3.out",
        stagger: 0.08,
        clearProps: "transform,opacity",
      });
    }, rootRef);
    const safety = window.setTimeout(() => {
      gsap.set("[data-intro-item]", { autoAlpha: 1, y: 0, clearProps: "all" });
    }, 1200);
    return () => {
      window.clearTimeout(safety);
      ctx.revert();
    };
  }, []);

  return (
    <div
      ref={rootRef}
      className="judah-glass judah-grid-bg relative overflow-hidden rounded-[var(--radius-xl)] p-6 md:p-10"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -top-24 -right-24 size-72 rounded-full bg-[var(--accent)] opacity-25 blur-3xl animate-pulse-slow"
      />
      <div className="relative flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="space-y-4">
          <span data-intro-item className="judah-chip">
            <span className="size-1.5 rounded-full bg-[var(--accent)]" />
            {eyebrow}
          </span>
          <h1
            data-intro-item
            className="judah-display max-w-3xl text-balance text-3xl leading-[1.05] tracking-tight md:text-5xl"
          >
            {title}
          </h1>
          <p
            data-intro-item
            className="max-w-2xl text-pretty text-sm leading-7 text-[var(--ink-700)] md:text-base"
          >
            {description}
          </p>
        </div>
        {action ? (
          <div data-intro-item className="shrink-0">
            {action}
          </div>
        ) : null}
      </div>
    </div>
  );
}
