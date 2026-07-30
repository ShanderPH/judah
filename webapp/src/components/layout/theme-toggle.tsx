"use client";

import { Button } from "@heroui/react";
import { Moon, Sun } from "lucide-react";
import { useRef, useSyncExternalStore } from "react";

import { gsap, useGSAP } from "@/src/lib/motion/use-gsap";

type Theme = "light" | "dark";

const subscribe = (notify: () => void) => {
  if (typeof window === "undefined") return () => {};
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
};

const getSnapshot = (): Theme =>
  (document.documentElement.dataset.theme as Theme) || "light";

const getServerSnapshot = (): Theme => "light";

const THEME_COLOR_PROPERTIES = [
  "--background",
  "--foreground",
  "--surface",
  "--surface-foreground",
  "--surface-secondary",
  "--surface-secondary-foreground",
  "--surface-tertiary",
  "--surface-tertiary-foreground",
  "--overlay",
  "--overlay-foreground",
  "--default",
  "--default-foreground",
  "--muted",
  "--accent",
  "--accent-foreground",
  "--success",
  "--success-foreground",
  "--warning",
  "--warning-foreground",
  "--danger",
  "--danger-foreground",
  "--info",
  "--info-foreground",
  "--border",
  "--separator",
  "--focus",
  "--link",
  "--scrollbar",
  "--field-background",
  "--field-foreground",
  "--field-placeholder",
  "--field-border",
  "--backdrop",
  "--surface-shadow",
  "--overlay-shadow",
  "--field-shadow",
] as const;

function readThemeValues(root: HTMLElement): Record<string, string> {
  const styles = getComputedStyle(root);
  return Object.fromEntries(
    THEME_COLOR_PROPERTIES.map((property) => [property, styles.getPropertyValue(property).trim()]),
  );
}

function clearInlineThemeValues(root: HTMLElement): void {
  for (const property of THEME_COLOR_PROPERTIES) root.style.removeProperty(property);
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const iconRef = useRef<HTMLSpanElement | null>(null);
  const timelineRef = useRef<gsap.core.Timeline | null>(null);
  const isAnimatingRef = useRef(false);
  const toggleRef = useRef<() => void>(() => {});

  useGSAP(
    (_, contextSafe) => {
      if (!contextSafe) return;

      const applyTheme = (next: Theme) => {
        document.documentElement.dataset.theme = next;
        document.documentElement.style.colorScheme = next;
        try {
          localStorage.setItem("judah-theme", next);
        } catch {
          // Storage can be unavailable in hardened/private browsing contexts.
        }
      };

      toggleRef.current = contextSafe(() => {
        if (isAnimatingRef.current) return;
        const current = getSnapshot();
        const next: Theme = current === "dark" ? "light" : "dark";
        const icon = iconRef.current;
        const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

        if (!icon || reduceMotion) {
          applyTheme(next);
          return;
        }

        const documentRoot = document.documentElement;
        const currentValues = readThemeValues(documentRoot);
        applyTheme(next);
        const targetValues = readThemeValues(documentRoot);
        for (const [property, value] of Object.entries(currentValues)) {
          documentRoot.style.setProperty(property, value);
        }
        isAnimatingRef.current = true;

        const finish = () => {
          clearInlineThemeValues(documentRoot);
          gsap.set(icon, { clearProps: "opacity,visibility,scale,willChange" });
          isAnimatingRef.current = false;
        };

        timelineRef.current = gsap
          .timeline({ onComplete: finish, onInterrupt: finish })
          .to(documentRoot, {
            ...targetValues,
            duration: 0.55,
            ease: "sine.inOut",
            overwrite: true,
          })
          .fromTo(
            icon,
            { autoAlpha: 0.35, scale: 0.92 },
            {
              autoAlpha: 1,
              scale: 1,
              duration: 0.35,
              ease: "sine.out",
              willChange: "opacity,transform",
            },
            0.08,
          );
      });

      return () => {
        timelineRef.current?.kill();
        clearInlineThemeValues(document.documentElement);
        toggleRef.current = () => {};
      };
    },
    { scope: rootRef },
  );

  return (
    <span ref={rootRef} className="contents">
      <Button
        isIconOnly
        variant="tertiary"
        onPress={() => toggleRef.current()}
        aria-label={theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"}
        className="rounded-full"
      >
        <span ref={iconRef} className="grid place-items-center">
          {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </span>
      </Button>
    </span>
  );
}
