"use client";

import gsap from "gsap";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const node = ref.current;
    const tween = gsap.fromTo(
      node,
      { autoAlpha: 0, y: 12 },
      {
        autoAlpha: 1,
        y: 0,
        duration: 0.5,
        ease: "power3.out",
        clearProps: "all",
      },
    );
    const safety = window.setTimeout(() => {
      gsap.set(node, { autoAlpha: 1, y: 0, clearProps: "all" });
    }, 900);
    return () => {
      window.clearTimeout(safety);
      tween.kill();
    };
  }, [pathname]);

  return (
    <div ref={ref} className="contents">
      {children}
    </div>
  );
}
