# Snapshot pré-hotfix — 2026-07-28

Consulta somente leitura, sem PII e sem mutação de banco, fila, HubSpot ou
configuração.

## Identidade e saúde

- Supabase project: `HelpdeskDB` (`vmvjddgjyunywbfcbbig`).
- Estado: `ACTIVE_HEALTHY`.
- PostgreSQL reportado pelo projeto: `17.6.1.021` (o plano/stack ainda cita 16;
  a divergência deve ser corrigida na documentação de plataforma fora deste
  hotfix).
- Branch local: `hotfix/queue-status-schema-contract`.
- Base SHA local: `40fe5089db3be413071f0282b3b4680395474a76`.
- Railway CLI: sessão ausente; deployment SHA e flag
  `CONVERSATION_CYCLES_ENFORCED` não puderam ser reconsultados por esse canal.

## Catálogo e agregados

`new_conversations_queue_status_check` permanece:

```sql
CHECK ((queue_status = ANY (ARRAY['pending'::text, 'queued'::text])))
```

Agregados da fila ativa:

- `pending`, `cycle_id IS NULL`: 8;
- elegíveis para autoatribuição: 8;
- sem ciclo: 8;
- com tentativa histórica `completed`: 8.

## Logs

Os logs PostgreSQL das últimas 24 horas continuam exibindo violações de
`new_conversations_queue_status_check` em cadência aproximada de 60 segundos e
colisões de `conversation_instances_idempotency_key_key`. O diagnóstico do plano
permanece válido.

## Limites

- Nenhuma migration foi aplicada em produção.
- Nenhuma linha foi alterada, removida, reproduzida ou reatribuída.
- Nenhum owner HubSpot foi consultado ou modificado.
