"use client";

import { useEffect } from "react";

export function SmoothScrollProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let target = window.scrollY;
    let current = window.scrollY;
    let frame = 0;
    const ease = 0.12;
    let active = false;

    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      event.preventDefault();
      target = Math.max(
        0,
        Math.min(target + event.deltaY, document.documentElement.scrollHeight - window.innerHeight),
      );
      if (!active) loop();
    };

    const loop = () => {
      active = true;
      current += (target - current) * ease;
      window.scrollTo(0, current);
      if (Math.abs(target - current) > 0.5) {
        frame = requestAnimationFrame(loop);
      } else {
        window.scrollTo(0, target);
        active = false;
      }
    };

    const onResize = () => {
      target = window.scrollY;
      current = window.scrollY;
    };

    const onTouchStart = () => {
      cancelAnimationFrame(frame);
      active = false;
      target = window.scrollY;
      current = window.scrollY;
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("resize", onResize);
    window.addEventListener("touchstart", onTouchStart, { passive: true });

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("touchstart", onTouchStart);
    };
  }, []);

  return <>{children}</>;
}
