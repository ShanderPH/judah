import Link from "next/link";

export default function ForbiddenPage() {
  return (
    <main className="grid min-h-svh place-items-center px-6 text-center">
      <div className="space-y-4">
        <p className="judah-mono text-xs uppercase tracking-[0.3em] text-[var(--danger)]">403</p>
        <h1 className="text-3xl font-semibold">Acesso nao autorizado</h1>
        <p className="text-sm text-[var(--muted)]">Sua conta nao possui a capability exigida por esta rota.</p>
        <Link className="text-sm text-[var(--accent)] underline" href="/dashboard">Voltar ao dashboard</Link>
      </div>
    </main>
  );
}
