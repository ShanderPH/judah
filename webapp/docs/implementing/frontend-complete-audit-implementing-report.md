# Relatório de implementing — frontend complete audit

> Data: 2026-07-29
> Branch: `refactor/webapp-production-readiness`
> Base: `223ed5853bf1e2d159f02b1e99c6bde96b8d0660`
> Escopo concluído: Gates B a D (`BE-01` a `BE-05`, `FE-01` a `FE-06`, `OPS-01`, verificação local `V-01` a `V-03`)
> Estado: Gate D local concluído; aguardando revisão e autorização de staging/Gate E

## Resultado executivo

O primeiro gate autorizado do planning foi concluído. As três mutações P0 que desativavam autenticação global deixaram de ser públicas, as leituras administrativas passaram a negar viewer/agent antes da serialização e o helper de papéis agora rejeita identidades sem role explícita.

Sync e agendas foram colocados atrás de manager/admin e de uma fronteira transacional de auditoria. Ela registra ator, papel, ação, alvo, motivo, correlation ID, fingerprint, status e resposta sanitizada. Chaves de idempotência opcionais permitem replay sem repetir o efeito e rejeitam reuso com payload diferente.

Nenhum deploy, push, PR, merge, request de produção, acesso a HubSpot/Supabase ou teste em base não local foi executado.

## Matriz implementada

| Superfície | viewer | agent | manager | admin |
|---|---:|---:|---:|---:|
| Analytics agregado sem PII | leitura | leitura | leitura | leitura |
| Business hours e agenda — leitura | leitura | leitura | leitura | leitura |
| Tickets/fila com contato e owner | 403 | 403 | permitido | permitido |
| Agentes, métricas, time logs, reatribuições | 403 | 403 | permitido | permitido |
| Sync NOVO | 403 | 403 | permitido + audit | permitido + audit |
| Agenda especial — escrita | 403 | 403 | permitido + audit | permitido + audit |
| Perfil de outro usuário | 403 | 403 | 403 | permitido |
| Identidade autenticada sem `role` | 403 | 403 | 403 | 403 |

Anônimos recebem 401. Health, webhooks e endpoints próprios do ciclo de auth continuam como exceções públicas explícitas. Verificadores HMAC não foram alterados.

## Implementação entregue

- RBAC manager/admin em todas as operações do router administrativo de suporte.
- RBAC manager/admin nas superfícies de tickets e diagnóstico com PII/owner.
- RBAC admin no detail de usuário.
- Remoção de `auth=None` de sync, business hours e special schedules.
- Ledger `AdministrativeActionAudit` e migration reversível `0025`.
- Executor auditado, transacional e idempotente para sync/upsert/delete.
- Validação Pydantic v2 de tipo, horas e motivo de special schedules.
- Preservação de signatures de endpoints decorados para o Django Ninja.
- Testes de autorização positiva/negativa, payload, replay, PII e audit failure.

## Verificação

| Verificação | Resultado |
|---|---|
| Ruff check | passou |
| Ruff format check | passou |
| Mypy do escopo | passou, 7 arquivos |
| Suite local segura | 956 passed, 11 skipped |
| Cobertura | 90,42% (mínimo 90%) |
| Django system check | 0 issues |
| Migration drift | no changes detected |
| Banco usado | SQLite privado/descartável |

## Gate C — resultado de implementing

O refresh token deixou de trafegar na query string. `POST /auth/refresh` agora aceita exclusivamente `RefreshRequest` no corpo JSON, usa o contrato oficial de rotação do Ninja JWT, inclui o refresh rotacionado na resposta e invalida o token anterior quando blacklist está ativa. O teste integrado prova sucesso, rotação, replay 401, segunda rotação e rejeição do consumidor legado por query.

O payload de usuário passou a expor capabilities derivadas de uma policy backend conservadora. Viewer/agent recebem somente `dashboard.read`; manager recebe capabilities administrativas sem sandbox; admin recebe também `sandbox.use`. O backend continua sendo a autoridade dos endpoints.

No WebApp, cookies continuam HttpOnly, SameSite=Lax, Secure em produção e Path=/, agora com `maxAge` alinhado ao `exp` do JWT. O prefixo `__Host-` foi avaliado e adiado: a troca de nome forçaria relogin e Path=/ é necessário para layouts, auth handlers e BFF. Ausente, expirado, inválido, configuração ausente e backend indisponível possuem respostas distintas na fronteira server-side.

O catch-all do BFF foi mantido somente com policy versionada default-deny. Ele valida método/path/capability, origem, host, `Sec-Fetch-Site`, JSON e limite de 16 KiB; rejeita 404/405/413/415/403 antes de alcançar o Judah. Somente Content-Type, Idempotency-Key e correlation ID podem ser encaminhados; cookies, Authorization do browser e hop-by-hop headers não atravessam a fronteira.

Todas as rotas administrativas, incluindo `/agents`, são validadas no layout server-side. `/sandbox-chat` tem validação server-side própria e exige `sandbox.use`. Menu, sync, CRUD de agentes e assign/reassign usam o mesmo capability map. As mutações do cliente agora enviam Idempotency-Key.

### Verificação do Gate C

| Verificação | Resultado |
|---|---|
| Ruff auth | passou |
| Mypy auth | passou, 24 arquivos |
| Suite backend local segura | 961 passed, 11 skipped |
| Cobertura backend | 90,43% |
| Testes frontend | 10 passed em 4 arquivos |
| ESLint | passou |
| TypeScript strict | passou |
| Next production build | passou |
| Smoke HTTP local | rotas protegidas retornaram 307 para login; BFF desconhecido retornou 404; mutação cross-site retornou 403 |
| Busca por refresh na URL | nenhum consumidor ativo; ocorrência restante somente no teste negativo backend |
| `git diff --check` | passou |

A conexão da skill de browser falhou antes de abrir a sessão local (`kernel assets` indisponíveis). Não há screenshot/recording autenticado neste gate; o smoke equivalente foi executado por HTTP local e a matriz por capability foi coberta unitariamente. A verificação browser autenticada continua obrigatória antes de release.

O finding anterior de Next/sharp foi resolvido no Gate D descrito abaixo.

## Gate D — supply chain, headers, logging e CI

Next.js e `eslint-config-next` foram reconciliados em 16.2.12. Como o Next corrigido ainda declara `sharp ^0.34.5`, o lock usa override explícito para 0.35.0. `npm ci`, `npm ls` e o build provaram a combinação, enquanto `npm audit --omit=dev --audit-level=high` retornou zero vulnerabilidades. `turbopack.root` removeu a inferência incorreta causada por lockfile fora do repo.

A CSP foi adicionada em report-only. O bootstrap de tema usa hash SHA-256 compartilhado com o layout, e apenas `/sandbox-chat` recebe origens HubSpot para script/connect/frame/image. `object-src`, `base-uri`, `form-action` e `frame-ancestors` são restritos; `nosniff`, referrer policy e permissions policy são globais. Auth, BFF, token HubSpot e páginas administrativas usam no-store. HSTS permanece desabilitado até validação da topologia.

Os Route Handlers sensíveis agora usam logger JSON allowlisted, não registram erro/body arbitrário e devolvem/propagam `X-Request-ID`. O backend Judah já possuía `common.logging` com structlog, scrub e contexto, então não foi criada uma segunda abstração. A política operacional de acesso/retenção foi documentada.

O CI raiz ganhou lane WebApp com `npm ci`, lint, typecheck, Vitest/JUnit, build e audit de produção.

### Verificação local do Gate D

| Verificação | Resultado |
|---|---|
| instalação determinística | `npm ci` passou |
| árvore | Next/eslint-config 16.2.12; sharp 0.35.0; sem ELSPROBLEMS |
| audit produção | zero vulnerabilidades |
| ESLint / TypeScript | passaram |
| Vitest | 17 passed em 7 arquivos |
| build | passou, 15 rotas, sem warning de root |
| smoke HTTP | CSP report-only, sandbox policy, no-store e request ID comprovados |

A parcela staging de V-03 não foi executada: exige autorização própria para ambiente, identidade por papel, logs externos e sandbox real.

## Gates E e F — implementação local

O scroll global interceptado foi removido, assim como grain animado, background fixo, fontes não usadas e parte do blur. A carga inicial de dashboard, agents, metrics e auto-assignment agora usa DAL `server-only` e acesso direto ao Judah; as ilhas cliente recebem o snapshot inicial sem duplicar a primeira leitura. Fontes complementares falham de forma isolada e produzem aviso degradado.

O cliente preserva o envelope paginado real do Django Ninja. A fila navega por offset em lotes de 40, mostra X–Y de Z e cancela corridas. Retry/backoff é restrito a GET transitório; writes não são repetidos automaticamente.

No Gate F, ações sensíveis receberam confirmação explícita; force-reassign exige motivo. Filtros exclusivos usam RadioGroup do HeroUI v3, gráficos têm alternativa tabular, reduced motion é respeitado, os tokens semânticos principais usam `oklch` e foram adicionados loading/error/global-error/not-found. O catálogo mínimo está em `docs/design-system/judah-component-contracts.md`.

Verificação local: 19 testes, lint, typecheck, build, audit de produção com zero vulnerabilidades e smokes HTTP passaram. A evidência completa está em `docs/verification/frontend-gates-e-f-local.md`.

## Pendências intencionais

O browser oficial não encontrou uma instância disponível, portanto V-04/V-05 seguem incompletos quanto a screenshot/recording, axe, teclado/screen reader autenticado e métricas Web Vitals/long tasks. Staging e deploy não foram iniciados.

Todo drift preexistente fora do escopo foi preservado e não deve ser incluído em eventual commit/PR desta request.

## Próxima decisão

Disponibilizar o in-app Browser e repetir V-04/V-05 autenticado. Somente após essa evidência e a aprovação explícita do Gate G devem ser considerados staging/deploy. Push, PR, merge e deploy continuam gates separados.

## Atualização — tentativa de Gate G (2026-07-30)

O Gate G foi analisado até o limite seguro de `OPS-02`. A instalação determinística, 24 testes, lint, TypeScript, build Next.js 16.2.12 de 15 rotas, audit de produção e `git diff --check` passaram novamente. O build local final recebeu o identificador `Qo87kOf8uJ-3fd0QE6Vy_`. Um `next start` temporário também comprovou `/login` 200 com headers, `/dashboard` 307 para login e BFF desconhecido 404; o processo local foi encerrado após o smoke.

A readiness não foi aprovada. O SHA atual `223ed5853bf1e2d159f02b1e99c6bde96b8d0660` antecede toda a implementação, que permanece sem commit; a migration `0025` também não pertence a um release candidate. A inspeção read-only do Railway encontrou somente o ambiente `production` e os serviços backend/worker/beat/Redis, sem serviço WebApp. O backend ativo está no SHA `c658b74a57b9813c850a3a6ae1dd0e646c51b31b`, que não contém esta request.

O browser sub-agent repetiu o fluxo oficial, mas a runtime retornou `No browser is available` e descoberta `[]`; também não há fixture autenticada descartável documentada. V-04/V-05 permanecem abertos. O audit de produção está limpo, mas uma advisory nova faz o audit completo reportar 9 entradas high dev-only no encadeamento ESLint/minimatch; a correção automática restante exige ESLint 10 e não foi forçada. O resultado de readiness e o rollback proposto foram registrados em `docs/deployment/frontend-gate-g-readiness.md`. Nenhum commit, push, PR, merge, staging ou deploy foi executado.
