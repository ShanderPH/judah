# Revisão e hotfix do PR #134 — 2026-10-02

## Objetivo e evidências

PR: https://github.com/ShanderPH/judah/pull/134. HEAD inicial: `2c59d8f9da0e92a8d5a7f72da052fa2c369f6aa1`, base `main`. A revisão usa o baseline de produção como registro histórico, sem renovar suas contagens ou afirmar nova convergência remota.

Na coleta inicial não havia reviews nem comentários inline. Os comentários gerais eram Vercel com preview Ready e CodeRabbit informando que ignorou o draft; esse check verde não constitui revisão de código. Durante esta execução, o PR passou externamente a ready for review, e o CodeRabbit iniciou análise. O hotfix preserva o estado de revisão escolhido no GitHub.

CI inicial: Python, lint/mypy, Django e security aprovados; WebApp falhou somente na auditoria de produção. Log: https://github.com/ShanderPH/judah/actions/runs/36998167334/job/110809543051.

## Achados e correções

### OPS-01 — dependência vulnerável, corrigida

Next.js 16.3.4 estava na faixa afetada de [GHSA-vcvr-r3jv-pc5j](https://github.com/advisories/GHSA-vcvr-r3jv-pc5j), vulnerabilidade crítica em ImageResponse. Atualizados `webapp/package.json` e `webapp/package-lock.json` para Next.js 16.3.8 e preset ESLint da mesma versão. O gate `npm audit --omit=dev --audit-level=high` foi preservado.

### BE-01 — entrada não alcançada pelo scanner, corrigida

`record_proven_occurrence` agendava somente closes. Uma entrada recusada por `open_or_get_cycle` podia permanecer pending sem horário. `task_scan_lifecycle_occurrences` exigia horário vencido e nunca selecionava essa entrada.

Entradas comprovadas agora recebem agendamento na criação. O scanner também seleciona entradas pending sem agendamento, para alcançar rows antigas. Os budgets de retry e idade são avaliados antes da projeção; rows expiradas vão para repair, sem replay histórico. Owners sem agendamento continuam fora desse fallback.

### BE-01 — retry de entrada interpretado como fechamento, corrigido

`task_reconcile_lifecycle_occurrence` distinguia owner e tratava os demais tipos como close. O hotfix adiciona um ramo explícito de entrada que usa `open_from_proven_occurrence`, preservando account/ticket/time/event da ocorrência. Created/duplicate convergem; conflitos e stale mantêm o orçamento existente. Evidência de entrada não proven nunca é usada como fechamento.

### Backlog e CD — pendentes

Os 229 owners e 15 closes em repair relatados no baseline dependem de classificação e autorização próprias. A compatibilidade temporal de 24 owners não comprova, sozinha, identidade histórica de owner ou autorização para replay.

As três entradas antigas, caso permaneçam além do limite de idade no deploy, serão alcançadas e classificadas como repair. A recuperação do scanner não comprova que essas três rows foram resolvidas em produção.

`.github/workflows/cd.yml` depende do CI, mas seus passos de migração/deploy são mensagens placeholder. Um status verde desse workflow não comprova deploy Railway. Conferir API/worker/beat no mesmo SHA pelo gate operacional já existente, após autorização. Esta revisão não altera o mecanismo de deploy.

## Verificação local

Ambiente: checkout isolado `/tmp/judah-pr134-review`; Python 3.14.7, PostgreSQL 16 local em `127.0.0.1:5433`, Redis 8.6 local e Node 24.21.0. Testes somente em SQLite privado e banco PostgreSQL descartável `judah_test`.

| Gate | Resultado |
|---|---|
| RED antes do patch | 8 falhas / 2 passes nos primeiros testes de regressão |
| Suíte completa SQLite final | 1.016 passed / 50 skipped; cobertura 90,75% |
| Regressões finais PostgreSQL | 52 passed, incluindo 12 casos de entrada |
| Ruff check / format | aprovados, 384 arquivos formatados |
| mypy apps/common/core | aprovado, 381 arquivos |
| Django check / migration drift | sem issues / sem mudanças |
| npm ci | aprovado; lockfile reproduzível |
| ESLint / tsc | exit 0 / aprovado |
| Vitest | 66 testes, 11 arquivos aprovados |
| Next.js production build | aprovado em 16.3.8 |
| npm audit de produção | zero vulnerabilidades |

O preset ESLint atualizado sinaliza um aviso no hook preexistente `webapp/src/hooks/use-api-query.ts` pelo redirecionamento via `window.location.assign`. A mudança do fluxo de autenticação não integra este hotfix. Vitest também avisa sobre um futuro loader nativo; npm 12 sinaliza script postinstall não aprovado de `unrs-resolver` e achados em dependências de desenvolvimento. Esses avisos não impediram os gates acima. A auditoria zero refere-se exclusivamente às dependências de produção.

O build no sandbox não avançou; a execução fora do sandbox concluiu. A primeira tentativa PostgreSQL no sandbox falhou ao conectar; a repetição contra a mesma instância local fora do sandbox passou.

## Comandos de reprodução

Da raiz do checkout, com `.venv` Python 3.14 e dependências instaladas:

```bash
SALOMAO_V1_BASE_URL='' .venv/bin/python run_tests_local.py
DJANGO_ENV=test DJANGO_SECRET_KEY=local-test-key DATABASE_URL=postgresql://judah:judah_dev_password@127.0.0.1:5433/judah_test SALOMAO_V1_BASE_URL='' SENTRY_DSN='' AGNO_TELEMETRY=false .venv/bin/python -m pytest apps/support/tests/test_lifecycle_entry_recovery.py apps/support/tests/test_provider_contract_red.py apps/support/tests/test_assignment_provenance_postgres.py -q --no-cov --maxfail=1
.venv/bin/ruff check .
.venv/bin/ruff format --check .
DJANGO_ENV=test DJANGO_SECRET_KEY=local-test-key DATABASE_URL=sqlite:///./.test.sqlite3 SALOMAO_V1_BASE_URL='' SENTRY_DSN='' .venv/bin/mypy apps common core
DJANGO_ENV=test DJANGO_SECRET_KEY=local-test-key DATABASE_URL=sqlite:///./.test.sqlite3 SALOMAO_V1_BASE_URL='' SENTRY_DSN='' .venv/bin/python manage.py check --fail-level WARNING
DJANGO_ENV=test DJANGO_SECRET_KEY=local-test-key DATABASE_URL=sqlite:///./.test.sqlite3 SALOMAO_V1_BASE_URL='' SENTRY_DSN='' .venv/bin/python manage.py makemigrations --check --dry-run
npm --prefix webapp ci
npm --prefix webapp run lint
npm --prefix webapp run typecheck
npm --prefix webapp test
npm --prefix webapp run build
npm --prefix webapp audit --omit=dev --audit-level=high
```

As credenciais PostgreSQL acima são as defaults públicas do serviço Docker local versionado. No checkout de revisão, os executáveis Python usados foram os da `.venv` do workspace original, com cwd apontando para o checkout.

## Decisão

Os critérios locais do suplemento `01-plan/pr-134-hotfix.md` estão cobertos. O PR passa a conter o hotfix e a correção de supply chain, mantendo o baseline original e preservando o estado de revisão no GitHub. V-03 e ARCH-03 permanecem abertos. A request principal continua em VERIFY até deploy autorizado, nova observação e classificação do backlog; nenhuma operação remota de dados foi executada.
