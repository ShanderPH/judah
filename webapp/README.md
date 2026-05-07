# Judah WebApp

Painel administrativo em Next.js 16.2.4 para o Judah.

## Stack

- Next.js 16.2.4
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
```

Se o backend estiver em outra origem, ajuste o valor.

## Rodar localmente

```bash
npm install
npm run dev
```

Abra `http://localhost:3000`.

## Validacao executada

```bash
npm run lint
npm run build
```

Os dois comandos passaram nesta implementacao.

## Estrutura principal

- `app/(public)/login/page.tsx`: tela publica de login
- `app/(app)/*`: area autenticada
- `app/api/auth/*`: login, sessao e logout com cookies `HttpOnly`
- `app/api/backend/[...path]/route.ts`: proxy autenticado para o Judah
- `src/features/*`: telas e logica de apresentacao
- `src/lib/api/*`: client tipado e agregadores de dados

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

## Lacunas do backend documentadas

- O backend autentica por `username`, nao por email de forma garantida.
- Nao existe endpoint de logout.
- Nao existe CRUD publico de agentes ou de regras avancadas de autoatribuicao.
- Nao existe endpoint de atribuicao manual ou redistribuicao administrativa.
- Nao existe leitura publica de `AgentMetrics`, `AgentDailyTimeLog` ou `ConversationReassignment`.
- `support/tickets/*` nao foi usado como base do painel porque o contrato atual esta inconsistente com os modelos do backend.
