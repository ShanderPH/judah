# Handoff

## Resumo do implementado/corrigido

- Criei um novo app `webapp/` em Next.js 16.2.4 com App Router, TypeScript, HeroUI v3.0.3 e GSAP.
- Implementei autenticacao via backend Judah com cookies `HttpOnly`, login, sessao, logout local e proxy autenticado para as APIs do backend.
- Entreguei as telas de login, dashboard, fila, autoatribuicao e metricas usando somente endpoints reais mapeados na analise.
- Estruturei a camada web em `features`, `components`, `lib/api`, `lib/auth` e `types` para separar UI, integracao e estado.
- Documentei lacunas reais do backend e evitei inventar acoes administrativas sem API correspondente.

## Arquivos modificados

- `webapp/app/*`
- `webapp/proxy.ts`
- `webapp/src/components/*`
- `webapp/src/features/*`
- `webapp/src/hooks/use-api-query.ts`
- `webapp/src/lib/*`
- `webapp/src/types/api.ts`
- `webapp/package.json`
- `webapp/package-lock.json`
- `webapp/README.md`

## Como testar localmente

```bash
cd webapp
npm run dev
```

Acesse `http://localhost:3000`.

Configure antes:

```bash
JUDAH_API_URL=http://127.0.0.1:8000/api/v1
```

Valide manualmente:

- login e redirecionamento para `/dashboard`
- navecacao entre `/dashboard`, `/queue`, `/auto-assignment` e `/metrics`
- refresh da sessao ao navegar
- botao `Sync NOVO` na tela de autoatribuicao

## Riscos conhecidos / areas frageis

- O backend autentica por `username`; a UI apresenta campo de email por requisito visual, mas ele e enviado como identificador do backend atual.
- `support/tickets/*` segue inconsistente com os modelos do backend e ficou fora do fluxo principal do painel.
- Nao ha browser sub-agent verification registrada nesta entrega.
- A validade do refresh depende do comportamento atual de `POST /auth/refresh?refresh=...`.

## Pontos de integracao criticos

- `app/api/backend/[...path]/route.ts`: proxy autenticado e refresh de token
- `app/api/auth/login/route.ts`: conversao do identificador para o contrato real do Judah
- `src/lib/api/overview.ts`: composicao das consultas usadas pelas telas
- Endpoints faltantes listados em `00-context/backend-analysis.md` e `webapp/README.md`
