# Gate C verification - cycle-aware ingestion and saga

**Data:** 2026-07-21
**PostgreSQL:** container local descartável PostgreSQL 16 em
`127.0.0.1:55432`; nenhum serviço compartilhado foi acessado.

## Evidência

| Prova | Resultado |
|---|---|
| PostgreSQL constraints/migration/concorrência | 59 passed |
| Regressão focada de ingestão e saga | 81 passed, 2 skips SQLite |
| Suíte completa local | 517 passed, 5 skips PostgreSQL-only |
| Ruff check / format | limpo; 264 arquivos |
| mypy | sem issues; 263 arquivos |
| Django check / migration drift | 0 issues / no changes detected |
| `git diff --check` | limpo |

## Stop gate

- owner mutation continua impossível sem reserva durável;
- webhook, propriedade atual, sync, single e drain convergem por ciclo;
- `external_applied` finaliza o ciclo original;
- ciclo stale aborta antes do provider e não vaza capacidade;
- SAT, ausência, FIFO e writer guards permanecem verdes.

Gate C concluído. Gate D, deploy, flags, backfill e mutações externas não
foram executados.
