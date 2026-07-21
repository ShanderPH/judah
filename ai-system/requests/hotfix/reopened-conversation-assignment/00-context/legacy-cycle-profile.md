# Legacy cycle profile — status de execução

**Request:** `hotfix/reopened-conversation-assignment`
**Data:** 21 de julho de 2026

## Status

O comando `profile_legacy_cycles` (DB-01) foi criado e validado **somente com
fixtures no banco local isolado** (SQLite `.test.sqlite3` via suite de
testes). Nenhum profiling foi executado contra staging, produção, Supabase ou
qualquer banco compartilhado, pois isso exige pré-aprovação conforme
`AGENTS.md` §11 e o master-plan §10.

**O perfil real dos dados legados permanece pendente de autorização.**

## Como executar após autorização

```powershell
# Somente após aprovação explícita do Felipe para a base alvo:
uv run python manage.py profile_legacy_cycles
```

O comando é read-only (bloco atômico sempre revertido), não chama o HubSpot e
emite apenas contagens agregadas sem PII, em JSON com chaves ordenadas.

## Métricas coletadas

Ver `02-artifacts/database/DB-01-legacy-cycle-profile.md` para a lista
completa das chaves emitidas e seus significados.
