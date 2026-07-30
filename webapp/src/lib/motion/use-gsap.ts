"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";

gsap.registerPlugin(useGSAP);

export const MOTION = {
  duration: {
    fast: 0.18,
    base: 0.42,
    slow: 0.72,
  },
  ease: {
    enter: "power3.out",
    exit: "power2.in",
    standard: "power2.inOut",
  },
} as const;

export { gsap, useGSAP };
