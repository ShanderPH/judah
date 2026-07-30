"use client";

import { Card } from "@heroui/react";
import type { LucideIcon } from "lucide-react";
import { useRef } from "react";

import { gsap, MOTION, useGSAP } from "@/src/lib/motion/use-gsap";

interface MetricCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  tone?: "default" | "accent" | "warning" | "danger" | "success";
}

const toneRing: Record<NonNullable<MetricCardProps["tone"]>, string> = {
  default: "from-[var(--accent)]/0 to-[var(--accent)]/0",
  accent: "from-[var(--accent)]/40 via-[var(--accent)]/10 to-transparent",
  warning: "from-[var(--warning)]/40 via-[var(--warning)]/10 to-transparent",
  danger: "from-[var(--danger)]/40 via-[var(--danger)]/10 to-transparent",
  success: "from-[var(--success)]/40 via-[var(--success)]/10 to-transparent",
};

export function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  tone = "default",
}: MetricCardProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const valueRef = useRef<HTMLParagraphElement | null>(null);

  useGSAP(
    (_, contextSafe) => {
      if (!contextSafe) return;
      const root = rootRef.current;
      if (!root) return;
      const media = gsap.matchMedia();

      media.add(
        {
          allowMotion: "(prefers-reduced-motion: no-preference)",
          finePointer: "(hover: hover) and (pointer: fine)",
        },
        (context) => {
          if (!context.conditions?.allowMotion || !context.conditions.finePointer) return;
          const rotateX = gsap.quickTo(root, "rotationX", {
            duration: MOTION.duration.base,
            ease: MOTION.ease.enter,
          });
          const rotateY = gsap.quickTo(root, "rotationY", {
            duration: MOTION.duration.base,
            ease: MOTION.ease.enter,
          });
          const lift = gsap.quickTo(root, "y", {
            duration: MOTION.duration.base,
            ease: MOTION.ease.enter,
          });

          gsap.set(root, { transformPerspective: 900, transformStyle: "preserve-3d" });
          const onMove = contextSafe((event: PointerEvent) => {
            const rect = root.getBoundingClientRect();
            rotateX(((event.clientY - rect.top) / rect.height - 0.5) * -5);
            rotateY(((event.clientX - rect.left) / rect.width - 0.5) * 7);
            lift(-4);
          });
          const onLeave = contextSafe(() => {
            rotateX(0);
            rotateY(0);
            lift(0);
          });

          root.addEventListener("pointermove", onMove);
          root.addEventListener("pointerleave", onLeave);
          return () => {
            root.removeEventListener("pointermove", onMove);
            root.removeEventListener("pointerleave", onLeave);
          };
        },
      );

      return () => media.revert();
    },
    { scope: rootRef },
  );

  useGSAP(
    () => {
      const node = valueRef.current;
      if (!node) return;
      const numeric = value.match(/-?[\d.,]+/)?.[0];
      if (!numeric || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        node.textContent = value;
        return;
      }
      const usesDecimalComma = numeric.includes(",");
      const usesGroupedThousands = !usesDecimalComma && /^-?\d{1,3}(?:\.\d{3})+$/.test(numeric);
      const normalized = usesDecimalComma
        ? numeric.replace(/\./g, "").replace(",", ".")
        : usesGroupedThousands
          ? numeric.replace(/\./g, "")
          : numeric;
      const decimalPlaces = usesDecimalComma
        ? (numeric.split(",")[1]?.length ?? 0)
        : usesGroupedThousands
          ? 0
          : (numeric.split(".")[1]?.length ?? 0);
      const target = Number(normalized);
      if (!Number.isFinite(target)) return;
      const prefix = value.slice(0, value.indexOf(numeric));
      const suffix = value.slice(value.indexOf(numeric) + numeric.length);
      const counter = { current: 0 };
      const formatter = new Intl.NumberFormat("pt-BR", {
        minimumFractionDigits: decimalPlaces,
        maximumFractionDigits: decimalPlaces,
      });
      gsap.to(counter, {
        current: target,
        duration: 0.9,
        ease: MOTION.ease.enter,
        onUpdate: () => {
          node.textContent = `${prefix}${formatter.format(counter.current)}${suffix}`;
        },
      });
    },
    { dependencies: [value], revertOnUpdate: true, scope: rootRef },
  );

  return (
    <div
      ref={rootRef}
      className="group relative"
    >
      <div
        aria-hidden
        className={`pointer-events-none absolute -inset-px rounded-[var(--radius-lg)] bg-gradient-to-br ${toneRing[tone]} opacity-0 transition-opacity duration-500 group-hover:opacity-100`}
      />
      <Card
        variant="default"
        className="judah-glass judah-grid-bg relative flex h-full flex-col gap-6 rounded-[var(--radius-lg)] p-5 md:p-6"
      >
        <div className="flex items-start justify-between gap-3">
          <p className="judah-mono text-[10px] uppercase tracking-[0.28em] text-[var(--muted)]">
            {label}
          </p>
          <span className="grid size-11 place-items-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--accent)] shadow-[var(--field-shadow)] transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:rotate-[-6deg]">
            <Icon className="size-5" strokeWidth={1.7} />
          </span>
        </div>
        <div className="space-y-1.5">
          <p ref={valueRef} className="text-balance text-3xl font-semibold tracking-tight md:text-4xl">
            {value}
          </p>
          <p className="text-sm leading-snug text-[var(--muted)]">{detail}</p>
        </div>
      </Card>
    </div>
  );
}
