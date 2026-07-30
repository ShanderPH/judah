"use client";

import { useRef } from "react";

import { gsap, MOTION, useGSAP } from "@/src/lib/motion/use-gsap";

interface PageIntroProps {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}

export function PageIntro({ eyebrow, title, description, action }: PageIntroProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  useGSAP(
    () => {
      const media = gsap.matchMedia();
      media.add("(prefers-reduced-motion: no-preference)", () => {
        const timeline = gsap.timeline();
        timeline
          .from("[data-intro-item]", {
            autoAlpha: 0,
            y: 24,
            duration: MOTION.duration.slow,
            ease: MOTION.ease.enter,
            stagger: 0.08,
            clearProps: "transform,opacity,visibility,willChange",
            willChange: "transform,opacity",
          })
          .from(
            "[data-intro-glow]",
            {
              autoAlpha: 0,
              scale: 0.7,
              duration: 1.1,
              ease: MOTION.ease.enter,
              clearProps: "transform,opacity,visibility,willChange",
            },
            0,
          );
      });
      return () => media.revert();
    },
    { scope: rootRef },
  );

  return (
    <div
      ref={rootRef}
      className="judah-glass judah-grid-bg relative overflow-hidden rounded-[var(--radius-xl)] p-6 md:p-10"
    >
      <div
        aria-hidden
        data-intro-glow
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
