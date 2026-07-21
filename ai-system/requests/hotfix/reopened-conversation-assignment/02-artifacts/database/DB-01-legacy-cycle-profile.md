# DB-01 — Profiling read-only de dados legados (Gate A)

**Data:** 21 de julho de 2026
**Escopo:** criação e validação local do comando. Nenhum profiling em base
compartilhada foi executado.

## O que foi implementado

- `apps/support/legacy_cycle_profile.py` — `collect_legacy_cycle_profile()`:
  agrega contagens inteiras, sem PII, via ORM SELECT-only. Consultas separadas
  da apresentação.
- `apps/support/management/commands/profile_legacy_cycles.py` — comando
  `profile_legacy_cycles`: executa a coleta dentro de `transaction.atomic()`
  com `set_rollback(True)` ao final, garantindo que nenhuma escrita persista,
  e imprime JSON com chaves ordenadas (saída determinística).

## Métricas produzidas (somente contagens agregadas)

- Totais de contexto: fila, atribuídos, fechados, tentativas, logs,
  reatribuições.
- Sobreposição entre tabelas: tickets em fila+atribuído, fila+fechado,
  atribuído+fechado e nas três simultaneamente.
- Assinatura do incidente: tentativa `completed` coexistindo com linha de
  fila ou de atribuído para o mesmo ticket.
- Multiplicidade: tickets com múltiplas tentativas, múltiplos logs e
  múltiplas tentativas vivas (esperado zero pela constraint parcial).
- Estado das tentativas: vivas (`LIVE_STATES` importado do serviço durável,
  sem duplicar a regra), `external_applied`, `repair_required`, `completed`.
- Correlação/provabilidade de timestamps: tentativa reservada antes da
  entrada na fila, fechamento anterior à atribuição, linhas de atribuído ou
  fechado sem `entered_queue_at`, fechados sem `assigned_at`.
- Proveniência: tentativas concluídas sem log e logs sem tentativa.

Não implementado por exigir autorização separada: divergência owner externo ×
estado local (consulta HubSpot) e qualquer conteúdo de
`00-context/legacy-cycle-profile.md` com dados reais.

## Garantias

- Somente `SELECT`/agregações; nenhuma escrita, correção, associação,
  fechamento, reabertura ou reconciliação.
- Nenhuma chamada HubSpot.
- Nenhum identificador, nome ou e-mail na saída — apenas inteiros.
- Rollback obrigatório do bloco atômico no comando.

## Testes

`apps/support/tests/test_legacy_cycle_profile.py` — 6 testes com fixtures no
banco local isolado (SQLite `.test.sqlite3`): contagens exatas em cenário com
sobreposição e assinatura do incidente, correlação de timestamps e lacunas de
proveniência, determinismo da saída, JSON ordenado do comando e prova de
read-only (contagens e linhas idênticas antes/depois).
