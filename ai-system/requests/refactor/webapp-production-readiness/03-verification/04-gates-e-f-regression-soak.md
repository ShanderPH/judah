# V-04/V-05 — regressões, soak e bloqueio de browser

> Data local: 2026-07-30
> Branch: `refactor/webapp-production-readiness`
> Escopo: correções e verificação local dos Gates E/F; Gate G, staging, deploy, push, PR e merge não autorizados.

## Resultado executivo

- A regressão de conexões ASGI foi corrigida com `CONN_MAX_AGE=0` nos perfis base e produção.
- Falhas HTTP 5xx de `/auth/me` e `/auth/refresh` agora são indisponibilidade upstream; não são classificadas como credenciais inválidas nem limpam cookies.
- Uma resposta 401 do recurso proxied tenta uma rotação de refresh e repete a chamada uma vez antes de limpar a sessão.
- GSAP foi removido do runtime e do lockfile; a atualização de estado durante renderização do `AppShell` foi removida; o script inline de tema segue o contrato de hidratação do Next 16.
- V-04 está tecnicamente avançado, mas não fechado: faltam LCP, INP, CLS, long tasks e inspeção desktop/mobile no browser.
- V-05 continua bloqueado: a runtime oficial retornou `No browser is available` e `agent.browsers.list()` retornou `[]`.

## Correções aplicadas

### Conexões ASGI

Arquivos: `core/settings/base.py`, `core/settings/production.py` e `core/tests/test_settings_environments.py`.

O parser de `DATABASE_URL` não cria mais conexões persistentes e produção não reativa `60 s` para porta 5432. O teste de perfis exige `CONN_MAX_AGE == 0` em staging e produção.

### Sessão e 401

Arquivos centrais: `webapp/src/lib/backend.ts`, `webapp/src/lib/auth/upstream-status.ts`, `webapp/app/api/auth/session/route.ts`, `webapp/app/api/backend/[...path]/route.ts` e `webapp/src/lib/auth/security-regression.test.ts`.

Somente 401/403 são rejeição de credencial. 5xx gera `BackendHttpError` e preserva cookies. O BFF usa o refresh atual, repete o request uma vez e só limpa cookies se a segunda resposta ainda for 401.

### Warnings e custo gráfico

GSAP e seu helper não existem mais na árvore (`npm ls gsap --depth=0` vazio). O `AppShell` não chama `setState` durante renderização, removendo a origem React compatível com o stack de `PressResponder`. O bootstrap inline informa tipo server/client e `suppressHydrationWarning`, conforme o guia atual do Next. A confirmação final do console ainda depende do browser oficial.

## Soak autenticado e conexões

Ambiente local reiniciado com Uvicorn ASGI em `127.0.0.1:8000`, Next production server em `127.0.0.1:3000`, PostgreSQL 16 e Redis locais em Docker.

| Prova | Resultado |
|---|---|
| Login, sessão, dashboard e métricas | 200 autenticado |
| Soak principal | 180 carregamentos, 199 s, 0 falhas |
| Soak complementar | 120 carregamentos, 79,3 s, 0 falhas |
| Carga final | 60 carregamentos, 25,9 s, concluída |
| Total | 360 carregamentos autenticados, 0 falhas |
| PostgreSQL após carga | 32 amostras: `total=1`, `active=1`, `idle=0` |

A conexão única observada era o próprio `psql` usado para consultar `pg_stat_activity`. Não houve conexão idle retida nem crescimento pós-carga em direção ao limite anterior de 100.

## Provas de sessão em runtime

- API desligada temporariamente: `GET /api/auth/session` retornou 502, `Cache-Control: no-store`, sem header `Set-Cookie`; a sessão não foi apagada.
- API religada e access token adulterado com refresh válido: `GET /api/auth/session` retornou 200 e emitiu novos cookies de access e refresh.

## Verificações automatizadas

| Verificação | Resultado |
|---|---|
| Backend completo | 961 passed, 11 skipped; cobertura 90,41% |
| Settings focado | 4 passed |
| Ruff check/format | passou |
| Django check | 0 issues |
| Migrations check | no changes |
| Vitest | 24 passed em 8 arquivos |
| ESLint | passou sem warnings |
| TypeScript strict | passou |
| Next production build | passou; 15 rotas |
| Audit produção | 0 vulnerabilidades |
| `git diff --check` | passou |
| Bundle pós-correção | 30 chunks JS, 1.523.120 bytes; GSAP ausente |

O mypy 2.1.0 produziu erro interno ao analisar diretamente `core/settings` sob Python 3.14; não foi reportado como aprovação. O TypeScript e a suíte backend completa permaneceram verdes.

## Estado de V-04

Concluído localmente: degradação isolada de analytics, paginação com fixture de 120 itens e offsets 0/40/80, cancelamento/retry idempotente, bundle pós-correção, soak autenticado e ausência de acúmulo de conexões.

Pendente por browser: desktop/mobile, requests duplicados pela timeline, LCP, INP, CLS, long tasks e dropped frames. Portanto V-04 não está formalmente concluído.

## Estado de V-05

Pendente: gravação autenticada, desktop/mobile, teclado completo, axe, screen reader e inspeção visual dos estados. A runtime oficial foi inicializada conforme a skill, o troubleshooting foi consultado e a descoberta final retornou `[]`. Nenhuma ferramenta externa foi usada como substituto.

Gate G permanece não iniciado e não autorizado.
