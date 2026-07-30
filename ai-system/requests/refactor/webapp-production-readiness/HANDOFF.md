# Handoff — Gates B a D de production readiness

## Resumo

- Gate B fechou mutações/leitura administrativas com RBAC fail-closed e ledger transacional.
- Refresh usa JSON body, rotação/blacklist e rejeita replay/query legado.
- BFF usa allowlist versionada, default-deny, origem/content type/body e capability.
- Rotas, menu e ações usam capabilities; `/agents` e `/sandbox-chat` são protegidas server-side.
- Cookies são server-only e mutações do cliente enviam Idempotency-Key.
- Next/sharp estão auditados, CSP está report-only, logs são sanitizados/correlacionados e o CI possui lane WebApp.

## Arquivos modificados

Backend em `apps/auth_user/*`, RBAC/audit do Gate B em `apps/support/*` e `common/permissions.py`. Frontend em `webapp/app/api`, layouts/rotas, `webapp/src/lib/auth`, `webapp/src/lib/api`, `webapp/src/lib/security`, `webapp/src/lib/observability`, componentes/features, tipos, package/lock, `next.config.ts` e testes Vitest. CI raiz e documentação de segurança também foram atualizados.

## Como testar

```powershell
uv run ruff check apps/auth_user apps/support common
uv run mypy apps/auth_user
uv run python run_tests_local.py
cd webapp
npm.cmd run test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npm.cmd audit --omit=dev --audit-level=high
```

Use somente os placeholders de `run_tests_local.py`; nunca aponte `DATABASE_URL` para host remoto.

## Verificação

Suite backend anterior: 961 passed, 11 skipped, cobertura 90,43%. Gate D: `npm ci`, ESLint, TypeScript, 17 testes Vitest, build Next, árvore Next 16.2.12/sharp 0.35.0, audit de produção com zero vulnerabilidades e `git diff --check` passaram. Smokes HTTP locais provaram CSP/header/no-store e request ID.

## Riscos e próximos ataques

- Migration do ledger foi validada em SQLite; PostgreSQL descartável/staging é gate separado.
- A verificação V-03 em staging ainda requer autorização explícita; CSP continua report-only e HSTS desabilitado.
- A runtime da skill de browser não inicializou; falta evidência visual autenticada antes do release.
- Drift preexistente em `ai-system/requests/hotfix/*`, `.hs/`, `Judah HubSpot Integration/` e `uv.lock` foi preservado.

Gate G, push, PR, merge, deploy e produção não foram executados.

## Atualização — correção do contrato paginado local (2026-07-30)

- O backend Django Ninja retorna paginação como `{items, count}`; a DAL server-side esperava `{results, count, next, previous}` e quebrava dashboard/métricas/agentes/autoassignment em `results[0]`.
- `webapp/src/lib/api/pagination.ts` agora normaliza ambos os envelopes no limite de transporte e deriva navegação por `limit/offset` quando o backend não fornece links.
- Cliente e DAL server-only usam o mesmo normalizador; payloads inválidos lançam erro para acionar os fallbacks/degradação existentes.
- Vitest: 21 testes em 8 arquivos; ESLint, TypeScript, build Next e `git diff --check` passaram.
- Smoke autenticado real: login, `/dashboard`, `/auto-assignment`, `/metrics`, `/agents` e `/queue` retornaram HTTP 200 sem o TypeError.
- Browser visual permaneceu bloqueado por `No browser is available`; nenhuma automação externa foi usada.

## Atualização — implementação local dos Gates E e F

- Scroll nativo substituiu o provider que interceptava wheel; grain/background fixo/fontes ociosas foram removidos e o blur foi reduzido.
- Dashboard, agentes, métricas e autoassignment recebem snapshot inicial de uma DAL `server-only`, diretamente do Judah, com degradação isolada por fonte.
- Paginação real preserva `count/next/previous/results`, navega em lotes de 40 e cancela requests obsoletos; retry automático é exclusivo de GET transitório.
- Ações sensíveis têm confirmação; force-reassign exige motivo; filtros usam RadioGroup e gráficos têm alternativa tabular/reduced motion.
- Tokens semânticos principais usam `oklch`; loading/error/global-error/not-found e catálogo mínimo foram adicionados.

### Arquivos centrais dos Gates E/F

- `webapp/src/lib/api/server-dal.ts`
- `webapp/src/lib/api/overview-loaders.ts`
- `webapp/src/hooks/use-api-query.ts`
- `webapp/src/features/queue/queue-management-view.tsx`
- `webapp/app/globals.css`
- `webapp/app/(app)/loading.tsx`
- `webapp/app/(app)/error.tsx`
- `webapp/app/global-error.tsx`
- `webapp/app/not-found.tsx`
- `webapp/docs/design-system/judah-component-contracts.md`
- `webapp/docs/verification/frontend-gates-e-f-local.md`

### Verificação e risco restante

Vitest (19), ESLint, TypeScript, build Next, audit de produção e smokes HTTP passaram. O browser sub-agent não encontrou uma instância de navegador disponível, logo screenshots/recording, axe, teclado/screen reader autenticado e Web Vitals/long tasks continuam pendentes. `STATUS.md` permanece em `VERIFY`; Gate G, staging, push, PR, merge e deploy não foram executados.

## Atualização — regressões ASGI/sessão e soak dos Gates E/F (2026-07-30)

- `CONN_MAX_AGE` agora é 0 em base e produção, conforme o contrato ASGI do Django.
- 5xx de autenticação preserva cookies; 401 de recurso tenta refresh e um único retry antes de invalidar a sessão.
- GSAP foi removido do bundle/lock; o setState durante renderização do `AppShell` e o contrato do script inline foram corrigidos.
- O ambiente local foi reiniciado e executou 360 carregamentos autenticados de dashboard/métricas sem falha. Trinta e duas amostras pós-carga de `pg_stat_activity` mostraram somente a conexão ativa da própria medição e zero idle.
- Backend completo: 961 passed, 11 skipped, cobertura 90,41%. Frontend: 24 Vitest, lint, TypeScript, build e audit de produção verdes.
- Evidência detalhada: `03-verification/04-gates-e-f-regression-soak.md`.

V-04 continua parcial e V-05 bloqueado porque a descoberta oficial de browsers retornou `[]`. Não há gravação, axe, teclado/screen reader, desktop/mobile ou Web Vitals de browser. O estado permanece `VERIFY`; Gate G continua não iniciado e não autorizado.

## Atualização — restauração do GSAP e Playwright MCP (2026-07-30)

- GSAP 3.15 e `@gsap/react` 2.1 foram restaurados como engine central, seguindo `useGSAP`, escopo por ref, context cleanup/contextSafe e `gsap.matchMedia()` para reduced motion.
- Transições de rota, fade dos tokens claro/escuro, feedback de botões, fades/staggers, cards, contadores, gráficos, sidebar, login e carrossel voltaram a usar GSAP; scroll permanece nativo.
- O carrossel pausa autoplay após interação e com reduced motion; o indicador anima dentro de um hit target estável para não quebrar automação.
- Frontend: 24 Vitest em 8 arquivos, ESLint, TypeScript, build de 15 rotas, audit de produção e `git diff --check` passaram.
- O Playwright MCP está operacional. Smoke público real em `/login` clicou o Slide 2, confirmou conteúdo/`aria-pressed`, transform GSAP ativo e zero warnings/errors no console.
- Os servidores temporários foram encerrados; portas 3000 e 8000 ficaram livres ao final.

O antigo `No browser is available` ainda descreve somente a runtime do in-app Browser. V-05 deixou de estar bloqueado por ausência total de ferramenta, mas continua incompleto: faltam autenticação, desktop/mobile, teclado, axe/screen reader, Web Vitals e gravação. Gate G continua não iniciado e não autorizado.

Revisão visual posterior removeu o reveal circular do tema. A implementação final faz fade/interpolação de 550 ms diretamente nos tokens de cor, borda, campo, backdrop e sombra, com crossfade discreto do ícone e troca imediata sob reduced motion.

## Atualização — V-04/V-05 e preparação do PR de produção (2026-07-30)

- Uma fixture SQLite descartável autenticada criou um admin local, dois agentes sintéticos e 105 atendimentos; o procedimento idempotente e sem senha versionada está em `webapp/docs/verification/local-ui-browser-fixture.md`.
- Playwright MCP cobriu desktop/mobile, teclado, axe, reduced motion, requests, performance, paginação até `81-105 de 105` e o diálogo de atribuição sem confirmar mutação.
- Findings do browser corrigiram contraste, landmarks/headings, foco do drawer mobile, warnings GSAP, redirects 308 do BFF e prefetch RSC duplicado.
- Evidência visual está em `webapp/docs/verification/artifacts/`; V-04/V-05 foram fechados localmente.
- Verificação final automatizada: backend 961 passed/11 skipped/90,41%; frontend 24 Vitest, lint, TypeScript, build de 15 rotas e audit de runtime com zero vulnerabilidades.
- O WebApp é hospedado no Vercel. O PR deve mirar `main`, branch observada de Vercel Production; commits do PR geram Vercel Preview para o smoke anterior ao merge.

Risco restante: o audit completo mantém 9 findings high dev-only na cadeia ESLint 9. O upgrade explícito para ESLint 10.8 foi testado sem `--force`, mas `eslint-config-next` 16.2.12 ainda inclui plugin React que usa a API removida `context.getFilename`; a versão 9.39.3 foi restaurada. O runtime audit permanece zerado. Checks, Vercel Preview e approval/code-owner review ainda precisam fechar no PR antes do merge/deploy.
