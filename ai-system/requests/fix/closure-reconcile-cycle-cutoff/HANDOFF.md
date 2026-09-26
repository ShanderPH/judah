# Handoff

## Resumo

- Corte derivado do primeiro `SupportConversationCycle.created_at` existente no banco.
- Eventos recebidos antes do corte saem do universo paginado; eventos com fechamento efetivo anterior ao corte não chegam ao reparo.
- A paginação conta só fechamentos com ciclo local temporalmente resolvido; casos sem ciclo ou com identidade incomparável são ignorados antes do serviço.
- Causas `no_cycle`, `identity_unavailable` e `conflict` aparecem separadas no JSON.
- Dry-run permanece padrão; `--apply` continua explícito.

## Arquivos modificados

- `apps/support/management/commands/reconcile_ticket_closures.py`
- `apps/support/tests/test_reconcile_ticket_closures.py`

## Como testar

- `python run_tests_local.py`
- `ruff check .`
- `ruff format --check .`
- `mypy apps/support/management/commands/reconcile_ticket_closures.py`
- `pre-commit run --all-files`

## Riscos e integração

- `legacy_skipped` é informativo por invocação, não uma métrica somável entre offsets.
- A primeira página elegível usa `ConversationEvent.created_at >= cutoff`, hora efetiva válida e um ciclo local com `entered_stage_at <= effective_at` e identidade consistente.
- Contadores de exclusão descrevem o prefixo examinado até preencher a página e se repetem em offsets posteriores.
- O dry-run de produção roda código local com variáveis de produção via `railway run`. Não valida um novo deploy.
