import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-svh place-items-center px-4">
      <section className="judah-glass max-w-lg rounded-[var(--radius-xl)] p-8 text-center">
        <p className="judah-mono text-xs uppercase tracking-[0.24em] text-[var(--accent)]">404</p>
        <h1 className="mt-3 text-3xl font-semibold">Pagina nao encontrada</h1>
        <p className="mt-3 text-sm text-[var(--muted)]">O endereco nao corresponde a uma rota disponivel do Judah.</p>
        <Link className="judah-focus-ring mt-6 inline-flex rounded-[var(--radius-md)] bg-[var(--accent)] px-4 py-2 font-semibold text-[var(--accent-foreground)]" href="/dashboard">Voltar ao dashboard</Link>
      </section>
    </main>
  );
}
