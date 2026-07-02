# `webapp/` — Frontend Next.js

## Resumo

Painel administrativo em Next.js 16 para o JUDAH. Fornece interface para login, dashboard, fila, agentes, auto-atribuição e métricas.

## Contexto

O frontend é um app separado dentro do monorepo. Ele não acessa o Supabase diretamente; todo acesso a dados passa pelo backend JUDAH via proxy interno.

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Framework | Next.js 16.2.4 |
| React | 19.2.4 |
| Linguagem | TypeScript |
| UI | HeroUI v3.0.3 |
| Styling | Tailwind CSS v4.2.4 |
| Animações | GSAP 3.15.0 |
| Ícones | Lucide React |

## Estrutura

```text
webapp/
├── app/
│   ├── (app)/              # Área autenticada
│   │   ├── dashboard/
│   │   ├── queue/
│   │   ├── agents/
│   │   ├── auto-assignment/
│   │   └── metrics/
│   ├── (public)/           # Área pública
│   │   └── login/
│   └── api/
│       ├── auth/           # login, session, logout
│       └── backend/[...path]  # proxy autenticado para JUDAH
├── src/
│   ├── components/         # Componentes reutilizáveis
│   ├── features/           # Telas e lógica de apresentação
│   ├── hooks/              # Hooks customizados
│   ├── lib/                # API client, auth, motion, utils
│   └── types/              # Tipagens
```

## Endpoints do backend consumidos

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

## Proxy backend

`app/api/backend/[...path]/route.ts` redireciona requisições autenticadas para `JUDAH_API_URL`, adicionando o access token JWT do cookie `HttpOnly`.

## Variáveis de ambiente

```bash
JUDAH_API_URL=http://127.0.0.1:8000/api/v1
```

## Arquivos relacionados

- [`webapp/README.md`](../../webapp/README.md)
- [`webapp/package.json`](../../webapp/package.json)
- [`webapp/next.config.ts`](../../webapp/next.config.ts)
- [`webapp/app/api/backend/[...path]/route.ts`](../../webapp/app/api/backend/[...path]/route.ts)

## Pontos de atenção

- O webapp documenta lacunas do backend: falta endpoint de logout, CRUD público de agentes, endpoints de `AgentMetrics`/`AgentDailyTimeLog`, atribuição manual/redistribuição administrativa.
- O contrato de `support/tickets/*` está inconsistente com os modelos do backend, segundo o README do webapp.

## Recomendações

- Alinhar schemas de tickets entre backend e frontend.
- Implementar endpoints necessários para o webapp.
- Adicionar testes E2E básicos no frontend.
