"use client";

import gsap from "gsap";
import { useEffect, useRef } from "react";

import { formatDateLabel } from "@/src/lib/utils/format";

export function SimpleBarChart({
  data,
}: {
  data: Array<{ label: string; value: number }>;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const max = Math.max(...data.map((item) => item.value), 1);

  useEffect(() => {
    if (!ref.current) return;
    const ctx = gsap.context(() => {
      gsap.from("[data-bar-fill]", {
        scaleX: 0,
        transformOrigin: "left center",
        duration: 0.9,
        ease: "power3.out",
        stagger: 0.04,
      });
      gsap.from("[data-bar-row]", {
        autoAlpha: 0,
        y: 12,
        duration: 0.5,
        ease: "power2.out",
        stagger: 0.04,
      });
    }, ref);
    return () => ctx.revert();
  }, [data]);

  return (
    <div ref={ref} className="space-y-3">
      {data.map((item) => (
        <div key={item.label} data-bar-row className="space-y-1.5">
          <div className="judah-mono flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-[var(--muted)]">
            <span>{formatDateLabel(item.label)}</span>
            <span className="text-[var(--foreground)]">{item.value}</span>
          </div>
          <div className="relative h-2.5 overflow-hidden rounded-full bg-[var(--default)]/60">
            <div
              data-bar-fill
              className="h-full rounded-full bg-gradient-to-r from-[var(--accent)] via-[var(--brand-500)] to-[var(--brand-300)] shadow-[0_0_24px_-4px_var(--accent)]"
              style={{ width: `${Math.max(6, (item.value / max) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export function SimpleLineChart({
  data,
}: {
  data: Array<{ label: string; value: number }>;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const pathRef = useRef<SVGPolylineElement | null>(null);

  const max = Math.max(...data.map((item) => item.value), 1);
  const min = Math.min(...data.map((item) => item.value), 0);
  const range = Math.max(max - min, 1);

  const points = data
    .map((item, index) => {
      const x = (index / Math.max(data.length - 1, 1)) * 100;
      const y = 100 - ((item.value - min) / range) * 100;
      return `${x},${y}`;
    })
    .join(" ");

  useEffect(() => {
    if (!pathRef.current) return;
    const length = pathRef.current.getTotalLength?.() ?? 0;
    if (!length) return;
    gsap.fromTo(
      pathRef.current,
      { strokeDasharray: length, strokeDashoffset: length },
      {
        strokeDashoffset: 0,
        duration: 1.4,
        ease: "power3.out",
      },
    );
  }, [points]);

  if (data.length === 0) return null;

  return (
    <div className="space-y-3">
      <svg
        ref={svgRef}
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="h-40 w-full overflow-visible rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)]/40 p-1"
      >
        <defs>
          <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--brand-500)" />
            <stop offset="100%" stopColor="var(--brand-300)" />
          </linearGradient>
        </defs>
        <polyline
          ref={pathRef}
          fill="none"
          stroke="url(#lineGrad)"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={points}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="judah-mono grid grid-cols-2 gap-2 text-[10px] uppercase tracking-[0.18em] text-[var(--muted)] md:grid-cols-4">
        {data.slice(-4).map((item) => (
          <div key={item.label} className="space-y-1">
            <p>{formatDateLabel(item.label)}</p>
            <p className="text-[var(--foreground)]">{item.value.toFixed(1)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
