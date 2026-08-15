# DB-01 — Migração das regras legadas

## Estratégia

A migration `0028` cria a agenda publicada e materializa, de forma idempotente, as fontes já existentes como regras editáveis:

- `BusinessHoursConfig` vira uma regra semanal por dia;
- o fechamento padrão de segunda a sexta é normalizado para 17:50;
- quinta-feira mantém os intervalos 09:00–12:00 e 13:00–17:50;
- feriados conhecidos de 2026 viram ausências;
- `SpecialSchedule` vira exceção de alta prioridade e pode sobrepor feriado.

## Garantias

- A migration não remove as tabelas legadas.
- O resolvedor conserva fallback legado quando não há regra nativa correspondente.
- Leituras sem agenda publicada não criam estado no banco.
- O versionamento da agenda e das regras permite detectar edições concorrentes.

## Rollback

O rollback da migration remove somente as tabelas nativas criadas por `0028`; as fontes legadas permanecem disponíveis. Antes de qualquer rollback em ambiente compartilhado, exportar as regras editadas após a migração.
