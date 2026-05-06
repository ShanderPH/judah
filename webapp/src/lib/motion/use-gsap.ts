"use client";

import gsap from "gsap";
import { useEffect, useRef, type DependencyList, type RefObject } from "react";

export function useGsapContext<T extends HTMLElement = HTMLElement>(
  setup: (ctx: gsap.Context) => void,
  deps: DependencyList = [],
): RefObject<T | null> {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const ctx = gsap.context(() => setup(ctx), ref);
    return () => ctx.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return ref;
}

export function staggerFadeUp(selector: string, options?: gsap.TweenVars) {
  return gsap.from(selector, {
    autoAlpha: 0,
    y: 28,
    duration: 0.85,
    ease: "power3.out",
    stagger: 0.08,
    ...options,
  });
}
