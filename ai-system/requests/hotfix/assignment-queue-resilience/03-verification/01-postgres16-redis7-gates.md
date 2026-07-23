# V-03/V-06 — PostgreSQL 16 e Redis 7 descartáveis

**Data:** 2026-07-23
**Ambiente:** containers locais sem volumes persistentes
**Produção/Supabase/Railway acessados:** não

## Topologia validada

- PostgreSQL: `postgres:16-alpine`, `127.0.0.1:55432`, banco `judah_test`.
- Redis: `redis:7-alpine`, `127.0.0.1:56379`, DB 15 nos testes de lock.
- Containers removidos após os testes; ambos usavam `--rm`.

## Falhas encontradas e corrigidas

O primeiro gate encontrou `FOR UPDATE cannot be applied to the nullable side
of an outer join` na convergência de owner manual. A query combinava
`select_for_update()` com `select_related("cycle")` sobre FK anulável. O lock
foi restringido à fila com `of=("self",)` e passou a usar `cycle_id`.

A corrida owner manual × reserva revelou risco de dupla capacidade. Tentativa
viva sem efeito agora é compensada antes da convergência manual; tentativa
`external_applied` para o mesmo owner é finalizada.

## Resultados

- Gate focado após correção PostgreSQL: `62 passed`.
- Redis owner-safe + protocolo/owner manual: `31 passed`.
- Corrida owner manual × reserva + Redis + concorrência: `14 passed`.
- Suite final PostgreSQL 16 + Redis 7: `540 passed`, zero skips, 93.35s.
- Ruff, formatação, mypy, Django check, migration check e diff check passaram.

## Invariantes comprovadas

- Dois workers não criam duas reservas para o mesmo ticket.
- A última unidade de capacidade é consumida no máximo uma vez.
- Owner manual concorrente não duplica capacidade nem projeção.
- Lua compare-and-delete libera imediatamente somente o token proprietário.
- Token alheio nunca é removido e todo lock tem TTL de recuperação.

## Resultado do gate

V-03 e V-06 aprovados. A request pode sair de VERIFY e aguardar autorização
separada para R0 read-only. Nenhum deploy, flag, dry-run compartilhado ou write
de produção foi executado.
