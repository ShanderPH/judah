"use client";

import { Button } from "@heroui/react";

export default function AppError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <section className="judah-glass rounded-[var(--radius-lg)] p-8" role="alert">
      <p className="judah-mono text-xs uppercase tracking-[0.2em] text-[var(--danger)]">Falha inesperada</p>
      <h1 className="mt-2 text-2xl font-semibold">Nao foi possivel renderizar esta area.</h1>
      <p className="mt-2 text-sm text-[var(--muted)]">Tente novamente. Se a falha persistir, use o identificador exibido nos logs correlacionados.</p>
      <Button className="mt-5" onPress={reset}>Tentar novamente</Button>
    </section>
  );
}
