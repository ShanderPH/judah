# Deploy — Integração Webapp ↔ API (Maio 2026)

Este guia cobre o deploy do conjunto de mudanças que liga o painel Next.js (`webapp/`) ao backend Django/Ninja em produção, removendo o "API Gap Ledger" e habilitando gestão completa de agentes, atribuições manuais, métricas granulares e logout real.

## 1. Mudanças entregues

### Backend (`apps/`, `core/`)
- `auth_user`: novo endpoint `POST /api/v1/auth/logout` que invalida o refresh token via `ninja_jwt.token_blacklist`.
- `support`: agentes (CRUD + reativar/inativar), capacidade `max_simultaneous_chats`, atribuição manual (`POST /support/queue/manual-assign/`) e force-reassign (`POST /support/queue/force-reassign/`).
- `support`: leituras públicas/admin para `agent_metrics`, `agent_daily_time_logs`, `conversation_reassignments` e agregações resumidas.
- `support`: serializers de `tickets/*` reescritos para casar com o modelo atual (UUID, `ticket_church`, `category`, `affected_*`, etc.).
- `core/settings/base.py`: `ninja_jwt.token_blacklist` adicionado a `INSTALLED_APPS` (migrations já existentes no pacote).

### Frontend (`webapp/`)
- `src/lib/api/client.ts` e `src/types/api.ts` cobrem 100% dos endpoints novos.
- `src/lib/api/overview.ts` removeu o `missingCapabilities` e passou a fan-out para os novos endpoints.
- `app/api/auth/logout/route.ts` agora chama `/auth/logout` no backend antes de limpar os cookies HttpOnly.
- Páginas atualizadas: `dashboard`, `queue`, `auto-assignment`, `metrics`. Página nova: `agents` (`/agents`).
- HeroUI v3 — Modal/Select/Switch/TextField — utilizado para fluxo de criação/edição de agente, atribuição manual e force-reassign.

## 2. Pré-requisitos

- Token CLI Railway configurado (`railway login`).
- Working tree limpo na branch que será mergeada para `main` (CI da Railway dispara em pushes para `main`).
- Variáveis de ambiente já provisionadas no projeto Railway (`DATABASE_URL`, `REDIS_URL`, `DJANGO_SECRET_KEY`, etc.).

## 3. Deploy do backend (Railway)

1. **Merge na branch principal** — `git push origin main`.
2. Railway dispara o build a partir do `Dockerfile` no projeto `judah-production`.
3. O `releaseCommand` configurado em `railway.toml` já roda:
   ```bash
   python manage.py migrate --noinput && python manage.py collectstatic --noinput --clear
   ```
   - **Importante:** as migrações de `token_blacklist` (`0001_initial` ... `0012_alter_outstandingtoken_user`) ficam pendentes assim que o app é instalado e serão aplicadas automaticamente nesse passo. Se quiser forçar manualmente antes, basta rodar `railway run python manage.py migrate token_blacklist`.
4. Validar pelo healthcheck: `curl https://judah-production.up.railway.app/api/v1/health/` deve retornar `200 OK`.
5. Smoke test dos endpoints novos:
   ```bash
   # Login
   curl -s -X POST https://judah-production.up.railway.app/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"username":"suporte_inchurch","password":"sup@rte123"}'

   # Listar agentes (use o access token retornado acima)
   curl -s https://judah-production.up.railway.app/api/v1/support/agents/ \
     -H "Authorization: Bearer <access_token>"

   # Resumo de metricas
   curl -s https://judah-production.up.railway.app/api/v1/support/metrics/agents/summary/?days=30 \
     -H "Authorization: Bearer <access_token>"

   # Logout (idempotente)
   curl -s -X POST https://judah-production.up.railway.app/api/v1/auth/logout \
     -H 'Content-Type: application/json' \
     -d '{"refresh":"<refresh_token>"}'
   ```

## 4. Deploy do frontend

O webapp pode ser publicado em qualquer host (Vercel, Railway, etc.). Variáveis necessárias:

| Var | Valor sugerido |
|-----|----------------|
| `JUDAH_API_URL` | `https://judah-production.up.railway.app/api/v1` |
| `NODE_ENV` | `production` |

> A variável `JUDAH_API_URL` é lida em `webapp/src/lib/backend.ts`. Sem ela o cliente cai no default `http://127.0.0.1:8000/api/v1`.

```bash
cd webapp
npm install
npm run build
npm run start
```

Para publicar na Railway no mesmo monorepo, basta adicionar um segundo serviço apontando para `webapp/Dockerfile` (ou usar o builder Nixpacks com `cd webapp && npm run build`). Em ambos os casos é obrigatório registrar `JUDAH_API_URL` apontando para o serviço Django.

## 5. Rollback

- Backend: `railway rollback` no painel ou redeploy do commit anterior. Os modelos de `token_blacklist` são aditivos e podem permanecer mesmo se a feature for revertida — a tabela vai apenas parar de ser populada.
- Frontend: redeploy da versão anterior. Caso o novo logout precise ser desligado temporariamente, basta substituir o body do `POST /api/auth/logout` por `jsonWithSession({ ok: true }, { clearCookies: true })` (comportamento original).

## 6. Pós-deploy

- Confirmar no painel Django Admin (ou via shell) que a tabela `token_blacklist_outstandingtoken` está sendo populada após cada login.
- Validar a página `/agents` autenticado como `suporte_inchurch` (admin) — fluxo de criação/edição/inativação deve concluir sem erros.
- Validar fluxo "Atribuir" e "Reatribuir" na página `/queue` com tickets reais ou um sandbox HubSpot.
- Garantir que os endpoints expostos passaram pelo CORS allowlist (`CORS_ALLOWED_ORIGINS`) caso o frontend rode em domínio novo.
