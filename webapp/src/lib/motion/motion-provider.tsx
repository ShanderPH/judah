"use client";

import { gsap, MOTION, useGSAP } from "@/src/lib/motion/use-gsap";

const INTERACTIVE_SELECTOR =
  "button:not(:disabled), [role='button']:not([aria-disabled='true']), [data-gsap-button]";

function resolveInteractiveTarget(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element ? target.closest<HTMLElement>(INTERACTIVE_SELECTOR) : null;
}

function movedWithinTarget(relatedTarget: EventTarget | null, target: HTMLElement): boolean {
  return relatedTarget instanceof Node && target.contains(relatedTarget);
}

export function MotionProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  useGSAP((_, contextSafe) => {
    if (!contextSafe) return;
    const media = gsap.matchMedia();

    media.add(
      {
        allowMotion: "(prefers-reduced-motion: no-preference)",
        finePointer: "(hover: hover) and (pointer: fine)",
      },
      (context) => {
        if (!context.conditions?.allowMotion) return;

        const animatedTargets = new Set<HTMLElement>();
        const animatePress = (target: HTMLElement, scale: number) => {
          animatedTargets.add(target);
          gsap.to(target, {
            scale,
            duration: MOTION.duration.fast,
            ease: MOTION.ease.enter,
            overwrite: "auto",
            transformOrigin: "center center",
            willChange: "transform",
          });
        };
        const animateHover = (target: HTMLElement, active: boolean) => {
          animatedTargets.add(target);
          gsap.to(target, {
            filter: active ? "brightness(1.045)" : "brightness(1)",
            duration: MOTION.duration.fast,
            ease: MOTION.ease.enter,
            overwrite: "auto",
            willChange: "filter",
          });
        };

        const onPointerOver = contextSafe((event: PointerEvent) => {
          if (!context.conditions?.finePointer) return;
          const target = resolveInteractiveTarget(event.target);
          if (!target || movedWithinTarget(event.relatedTarget, target)) return;
          animateHover(target, true);
        });
        const onPointerOut = contextSafe((event: PointerEvent) => {
          if (!context.conditions?.finePointer) return;
          const target = resolveInteractiveTarget(event.target);
          if (!target || movedWithinTarget(event.relatedTarget, target)) return;
          animateHover(target, false);
        });
        const onPointerDown = contextSafe((event: PointerEvent) => {
          const target = resolveInteractiveTarget(event.target);
          if (target) animatePress(target, 0.965);
        });
        const onPointerUp = contextSafe((event: PointerEvent) => {
          const target = resolveInteractiveTarget(event.target);
          if (target) animatePress(target, 1);
        });
        const onFocusIn = contextSafe((event: FocusEvent) => {
          const target = resolveInteractiveTarget(event.target);
          if (!target) return;
          animatedTargets.add(target);
          gsap.fromTo(target, { filter: "brightness(1.08)" }, {
            filter: "brightness(1)",
            duration: MOTION.duration.base,
            ease: MOTION.ease.enter,
            overwrite: "auto",
            clearProps: "filter,willChange",
          });
        });

        document.addEventListener("pointerover", onPointerOver, true);
        document.addEventListener("pointerout", onPointerOut, true);
        document.addEventListener("pointerdown", onPointerDown, true);
        document.addEventListener("pointerup", onPointerUp, true);
        document.addEventListener("pointercancel", onPointerOut, true);
        document.addEventListener("focusin", onFocusIn, true);

        return () => {
          document.removeEventListener("pointerover", onPointerOver, true);
          document.removeEventListener("pointerout", onPointerOut, true);
          document.removeEventListener("pointerdown", onPointerDown, true);
          document.removeEventListener("pointerup", onPointerUp, true);
          document.removeEventListener("pointercancel", onPointerOut, true);
          document.removeEventListener("focusin", onFocusIn, true);
          for (const target of animatedTargets) {
            gsap.killTweensOf(target);
            gsap.set(target, { clearProps: "filter,transform,willChange" });
          }
        };
      },
    );

    return () => media.revert();
  }, []);

  return children;
}
