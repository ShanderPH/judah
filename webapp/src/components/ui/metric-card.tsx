"use client";

import { Card } from "@heroui/react";
import gsap from "gsap";
import type { LucideIcon } from "lucide-react";
import { useEffect, useRef } from "react";

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
  const ref = useRef<HTMLDivElement | null>(null);
  const valueRef = useRef<HTMLParagraphElement | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (window.matchMedia("(hover: none)").matches) return;

    const setX = gsap.quickTo(node, "--rx", { duration: 0.4, ease: "power3.out" });
    const setY = gsap.quickTo(node, "--ry", { duration: 0.4, ease: "power3.out" });
    const setLift = gsap.quickTo(node, "y", { duration: 0.4, ease: "power3.out" });

    const handleMove = (event: MouseEvent) => {
      const rect = node.getBoundingClientRect();
      const offsetX = ((event.clientX - rect.left) / rect.width - 0.5) * 8;
      const offsetY = ((event.clientY - rect.top) / rect.height - 0.5) * -8;
      setX(offsetX);
      setY(offsetY);
      setLift(-4);
    };
    const handleLeave = () => {
      setX(0);
      setY(0);
      setLift(0);
    };
    node.addEventListener("mousemove", handleMove);
    node.addEventListener("mouseleave", handleLeave);
    return () => {
      node.removeEventListener("mousemove", handleMove);
      node.removeEventListener("mouseleave", handleLeave);
    };
  }, []);

  useEffect(() => {
    if (!valueRef.current) return;
    const numericMatch = value.replace(/[^\d.,-]/g, "").replace(",", ".");
    const target = Number(numericMatch);
    if (!Number.isFinite(target) || target === 0) return;
    const obj = { v: 0 };
    const prefix = value.match(/^[^\d-]+/)?.[0] ?? "";
    const suffix = value.match(/[^\d.,]+$/)?.[0] ?? "";
    const tween = gsap.to(obj, {
      v: target,
      duration: 1.1,
      ease: "power3.out",
      onUpdate: () => {
        if (!valueRef.current) return;
        const formatted = Math.round(obj.v).toString();
        valueRef.current.textContent = `${prefix}${formatted}${suffix}`;
      },
    });
    return () => {
      tween.kill();
    };
  }, [value]);

  return (
    <div
      ref={ref}
      className="group relative preserve-3d"
      style={
        {
          ["--rx" as string]: "0deg",
          ["--ry" as string]: "0deg",
          transform: "translate3d(0,0,0) rotateX(var(--ry)) rotateY(var(--rx))",
          transformStyle: "preserve-3d",
        } as React.CSSProperties
      }
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
          <p
            ref={valueRef}
            className="text-balance text-3xl font-semibold tracking-tight md:text-4xl"
          >
            {value}
          </p>
          <p className="text-sm leading-snug text-[var(--muted)]">{detail}</p>
        </div>
      </Card>
    </div>
  );
}
