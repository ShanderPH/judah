# Validação local

Ambiente: Python 3.14.7, banco SQLite local isolado por `run_tests_local.py`. O `conftest.py` elimina registros antes de cada teste; nenhum teste conectou a banco não local.

## Evidências

- Cliente CRM: os valores ISO-8601 da ocorrência real tornam-se `datetime` UTC aware; valores presentes sem timezone ou malformados falham na fronteira.
- Fluxo live em `SUPPORT_CAPACITY_MODE=enforce`: a primeira entrega materializa ciclo, `ClosedConversation` e occupancy; a segunda é `duplicate`; o log canônico registra `applied_current` com `domain_applied=true`.
- Reabertura posterior via `datetime` permanece `reopen_not_materialized`. Reconciliação de owner com `entered_closed_at` normalizado fecha as projeções uma vez.
- Os testes existentes de falha de lifecycle, provider e de atomicidade do PR #127 permanecem na suíte.

## Gates executados

- Focados (`test_crm_stage_timestamps.py`, `test_ticket_close_service.py`, `test_conversation_cycles.py`, `test_cycle_dual_write.py`): **101 aprovados, 3 ignorados**. Os ignorados exigem PostgreSQL local para conferir row locks.
- `python run_tests_local.py`: **927 aprovados, 46 ignorados**, cobertura **91,18%** (mínimo 90%).
- `ruff check .`: limpo.
- `ruff format --check .`: limpo após formatação do teste.
- `mypy apps core common`: 361 arquivos, sem problemas.
- `python manage.py makemigrations --check --dry-run`: `No changes detected`.
- `git diff --check`: limpo.

O teste de concorrência com row locks PostgreSQL não foi repetido neste checkout; os três cenários ficam ignorados no SQLite. O hotfix não altera os locks nem a transação do PR #127.
