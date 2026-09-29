# Gate operacional HubSpot Provider Contract 2026.09 — 2026-09-29

## Identidade e publicação

- `origin/main` em `871aa59b32a4457a060b5cd6ec9d655fe6136edd`; branch `fix/hubspot-provider-contract-scopes-preflight` criada desse HEAD em worktree limpo. Alterações locais preexistentes do checkout principal foram preservadas.
- `hs account list`: conta standard `47354717`. `hs project info --json`: projeto `102965355`, app `35466481`, UID `judah_hubspot_integration`, auth `STATIC`, build publicado inicialmente `20`.
- Download oficial read-only do build 20 mostrou oito scopes e subscriptions extras que não constavam dos manifests locais. O pacote de upload usou o build 20 como base; `diff -ru` antes do upload mostrou exclusivamente três scopes adicionados em `app-hsmeta.json`. Arquivo de webhooks permaneceu idêntico ao publicado.
- `hs project validate` passou. Build 21: `SUCCESS` e `DEPLOYABLE`. `hs project deploy --project='Judah HubSpot Integration' --build=21 --json` retornou `deployId=19`; `hs project info --json` confirmou `deployedBuildId=21`.
- Download oficial read-only do build 21 gerou [published-app.json](published-app.json) e [published-webhooks.json](published-webhooks.json). O comando `record_hubspot_webhook_readback` retornou `ready=true`, `app_uid_matches=true`, `missing_required_scopes=[]`, `unexpected_required_scopes=[]`, `webhook_uid_matches=true`, `target_url_matches=true`, `concurrency_matches=true` e `missing_active_subscriptions=[]`.
- Target publicado: `https://judah-production.up.railway.app/api/v1/webhooks/hubspot/`. Concorrência: `10`. Subscriptions obrigatórias ativas: `ticket.propertyChange` para `hs_v2_date_entered_939275049`, `hs_v2_date_entered_939275052` e `hubspot_owner_id`.
- Build 20 já tinha subscriptions adicionais, inclusive `hs_pipeline_stage` **inativa**. Nenhuma subscription foi adicionada, removida ou ativada neste trabalho.

## Token real e capabilities

Antes do reinstall, o preflight com credencial Railway real retornou `owners_read=forbidden`, `ready=false`; `hs project app-install-status --json` mostrou `isInstalledWithCurrentScopes=false`. Após `hs project install-app --json --force`, a releitura mostrou `isInstalledWithCurrentScopes=true` e incluiu os três scopes novos.

Executado localmente com variáveis do serviço `judah` em `production`:

```bash
railway run --project 18881041-8d59-4c99-a93b-c6f4f308e650 --environment production --service judah --no-local /home/felipe-teixeira/Workbench\ Febrate/judah/.venv/bin/python manage.py check_hubspot_provider_contract
```

[Resultado estruturado](production-preflight.json): `mode=off`, portal `47354717`, time `54655589`, `tickets_read=available`, `owners_read=available`, `teams_membership=available`, `users_read=available`, roster `complete=true`, 7 membros ativos `DEFAULT`, 0 owners ausentes, uma página, exit code `0`. Sete é valor observado na Teams API, sem constante local. O comando só usa GET; não grava CRM, cache ou domínio.

`tickets_write=unverified`: não havia sandbox/test account autenticado em `hs account list`, então nenhum PATCH foi feito. `HUBSPOT_TICKETS_WRITE_VERIFIED` não foi alterado. Mutation controlada em ticket de sandbox é bloqueio para ENFORCE, não para SHADOW. `conversations_read=not_found` pertence a spike opcional e não bloqueia este gate.

## Gates locais

- Suíte completa com SQLite local: **1003 passed, 47 skipped**. Skips dependem de Postgres/Redis/Celery locais.
- Testes focados do preflight: **16 passed**. Cobrem `off`, portal incorreto, Owners/Teams 403, roster parcial ou owner ausente, Owners >100, cursor malformado/repetido, ausência de write e saída/exit code. A suíte anterior do provider também cobria Teams 0/1/100/101, 401, 429 e 5xx.
- Ruff: limpo. Mypy: `Success: no issues found in 378 source files`. Django check: `0 silenced`. `makemigrations --check --dry-run`: `No changes detected`. Pre-commit dos arquivos alterados: todos os hooks aplicáveis passaram.
- `hs project validate`: passou antes e após a montagem do pacote de publicação.

## Método e limites

Interface Browser/Computer Use não estava disponível nesta sessão. Identidade, configuração publicada e instalação foram verificadas pelos comandos oficiais HubSpot CLI e pelo download do build implantado; nenhum readback foi inferido do manifesto local. Não houve deploy backend, backfill, `--apply`, mudança de flags ou mutation CRM.

**Gate técnico para revisão de promoção OFF para SHADOW:** `READY_FOR_SHADOW=true`. A promoção não foi executada. Estado da request maior continua `VERIFY` por ARCH-03 e prova de escrita em sandbox pendentes antes de ENFORCE.
