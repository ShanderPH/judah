"use client";

import { usePathname } from "next/navigation";
import { useRef } from "react";

import { gsap, MOTION, useGSAP } from "@/src/lib/motion/use-gsap";

export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const rootRef = useRef<HTMLDivElement | null>(null);

  useGSAP(
    () => {
      const media = gsap.matchMedia();
      media.add("(prefers-reduced-motion: no-preference)", () => {
        if (!rootRef.current) return;
        gsap.fromTo(
          rootRef.current,
          { autoAlpha: 0, y: 16, scale: 0.995 },
          {
            autoAlpha: 1,
            y: 0,
            scale: 1,
            duration: MOTION.duration.base,
            ease: MOTION.ease.enter,
            clearProps: "transform,opacity,visibility,willChange",
            willChange: "transform,opacity",
          },
        );
      });
      return () => media.revert();
    },
    { dependencies: [pathname], revertOnUpdate: true, scope: rootRef },
  );

  return (
    <div ref={rootRef} className="min-w-0" data-route-transition={pathname}>
      {children}
    </div>
  );
}
