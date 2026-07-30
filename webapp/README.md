# Judah WebApp

Painel administrativo em Next.js 16.2.12 para o Judah.

## Stack

- Next.js 16.2.12
- React 19
- TypeScript
- HeroUI v3.0.3
- GSAP

## Premissas de integracao

- O frontend nunca se conecta direto ao Supabase.
- Todo acesso a dados passa pelo backend Judah.
- O webapp encapsula os JWTs do backend em cookies `HttpOnly`.
- O navegador consome apenas rotas internas do app (`/api/auth/*` e `/api/backend/*`).

## Variaveis necessarias

Crie um `.env.local` dentro de `webapp/` com:

```bash
JUDAH_API_URL=http://127.0.0.1:8000/api/v1
NEXT_PUBLIC_HUBSPOT_PORTAL_ID=51734496
# The sandbox's official tracking code is loaded from
# https://js-na1.hs-scripts.com/51734496.js on /sandbox-chat.
# Server-only static private-app token (or OAuth access token) from the
# sandbox install. Requires
# conversations.visitor_identification.tokens.create.
HUBSPOT_SANDBOX_ACCESS_TOKEN=...
```

Se o backend estiver em outra origem, ajuste o valor.

## Rodar localmente

```bash
npm ci
npm run dev
```

Abra `http://localhost:3000`.

Para uma verificacao autenticada e descartavel no browser, siga
[`docs/verification/local-ui-browser-fixture.md`](docs/verification/local-ui-browser-fixture.md).
O procedimento usa somente banco local aprovado por `common.database_safety`,
nao versiona senha e cria dados suficientes para validar a terceira pagina da fila.

## Validacao executada

```bash
npm ci
npm run lint
npm run typecheck
npm test
npm run build
npm audit --omit=dev --audit-level=high
```

O CI executa a mesma sequencia com lockfile deterministico e publica o relatorio JUnit do Vitest.

## Seguranca operacional

- CSP inicia em `Content-Security-Policy-Report-Only`; `/sandbox-chat` recebe a allowlist HubSpot separada.
- Auth, BFF, sandbox e paginas administrativas usam `Cache-Control: no-store`.
- Logs server-side sao JSON, aceitam somente campos operacionais e propagam `X-Request-ID` ao Judah.
- HSTS permanece desabilitado ate a topologia HTTPS e todos os subdominios serem validados.
- A politica de acesso e retencao esta em `docs/security/logging-and-retention.md`.

## Estrutura principal

- `app/(public)/login/page.tsx`: tela publica de login
- `app/(app)/*`: area autenticada
- `app/api/auth/*`: login, sessao e logout com cookies `HttpOnly`
- `sandbox-chat`: rota isolada e autenticada para validar o widget da sandbox HubSpot
- `app/api/hubspot/visitor-token`: cria o Visitor Identification token no servidor
- `app/api/backend/[...path]/route.ts`: proxy autenticado para o Judah
- `src/features/*`: telas e logica de apresentacao
- `src/lib/api/*`: client tipado e agregadores de dados

`HUBSPOT_SANDBOX_OAUTH_ACCESS_TOKEN` continua aceito temporariamente como
fallback para deployments existentes. Prefira `HUBSPOT_SANDBOX_ACCESS_TOKEN`,
pois o projeto `inchurch-sandbox` usa autenticacao estatica de app privado.

## Endpoints usados

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`
- `GET /api/v1/health/`
- `GET /api/v1/support/queue/status/`
- `GET /api/v1/support/queue/pending/`
- `GET /api/v1/support/queue/assigned/`
- `GET /api/v1/support/queue/health/`
- `POST /api/v1/support/queue/sync-novo/`
- `GET /api/v1/support/queue/metrics/`
- `GET /api/v1/support/business-hours/`
- `GET /api/v1/support/special-schedules/`
- `GET /api/v1/analytics/reports/`

## Contratos administrativos

- O login aceita username ou email e a sessao do browser permanece encapsulada no BFF.
- Agentes, metricas, time logs, reatribuicoes e acoes de fila usam endpoints tipados e capabilities derivadas do papel.
- Atribuicao manual, force-reassign, sync e inativacao exigem confirmacao e registram auditoria administrativa.
- `support/tickets/*` nao e usado como base do painel; a fila segue os contratos dedicados de `support/queue/*`.
