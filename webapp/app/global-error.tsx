"use client";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="pt-BR">
      <body>
        <main style={{ display: "grid", minHeight: "100vh", placeItems: "center", padding: 24 }}>
          <section role="alert" style={{ maxWidth: 560 }}>
            <h1>O Judah encontrou uma falha inesperada.</h1>
            <p>Recarregue esta superficie. Nenhuma operacao sensivel sera repetida automaticamente.</p>
            <button type="button" onClick={reset}>Tentar novamente</button>
          </section>
        </main>
      </body>
    </html>
  );
}
