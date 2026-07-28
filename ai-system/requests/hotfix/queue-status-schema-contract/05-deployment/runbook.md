# Runbook — queue-status schema contract

## Pré-deploy

1. Confirmar autenticação, projeto, ambiente, serviços e SHA no Railway.
2. Confirmar `CONVERSATION_CYCLES_ENFORCED=false`.
3. Consultar, somente por agregados, valores distintos e contagens de
   `new_conversations.queue_status`.
4. Confirmar que não existem valores fora de `pending`, `queued`, `failed`.
5. Anexar prova PostgreSQL descartável de forward/backward ao Gate E.

## Deploy

O deploy e a aplicação da migration exigem autorização própria. Aplicar pelo
pipeline normal do JUDAH; não executar DDL manual em produção e não iniciar
replay/recovery como consequência implícita.

Após a migration, provar pelo catálogo:

```sql
SELECT pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'new_conversations'::regclass
  AND conname = 'new_conversations_queue_status_check';
```

A definição deve aceitar exatamente `pending`, `queued`, `failed`.

## Observação

Durante pelo menos dois ciclos de drain:

- acompanhar violações da CHECK e da UNIQUE do lifecycle;
- comparar agregados de fila, ciclos e tentativas antes/depois;
- confirmar que quarentena não cria `AssignmentAttempt` nem efeito HubSpot;
- não recuperar linha sem verificar antes o owner autoritativo no HubSpot.

## Rollback

- Preferir rollback do código por PR mantendo a CHECK ampliada, que continua
  compatível com `pending` e `queued`.
- Só reverter a migration após provar `count(*) = 0` para `queue_status='failed'`.
  A migration falha fechada se houver histórico `failed`.
- Não converter `failed` para outro estado, apagar fila ou reabrir efeitos como
  rollback automático.
- Se houver efeito externo inesperado, suspender somente o writer/serviço
  autorizado e preservar tentativas e logs.
