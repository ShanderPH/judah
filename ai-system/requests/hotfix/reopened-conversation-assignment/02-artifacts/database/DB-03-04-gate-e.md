# DB-03/DB-04 - Backfill e contrato por ciclo

## Entrega

O comando `backfill_conversation_cycles` processa uma lista ordenada de tickets
com limite e checkpoint `--after`. A mesma evidência persistida produz a mesma
`cycle_key`, e linhas já ligadas deixam de entrar no próximo lote. `--dry-run`
executa a lógica real dentro de transação marcada para rollback.

Precedência de correlação implementada:

1. projeção de fila ou atribuição com `entered_queue_at`;
2. fechamento com timestamps persistidos;
3. tentativa via fila, ciclo ativo ou ciclo fechado compatível;
4. log pela tentativa;
5. reatribuição dentro de uma única janela de ciclo.

Ausência ou multiplicidade de evidência gera quarentena no relatório. O comando
não importa cliente HubSpot, não muda owner e não consulta fonte externa.

A migration `0023_cycle_backfill_contract` adiciona proveniência de identidade,
permite `entered_stage_at` nulo apenas para legado identificado por evidência,
remove unicidades globais de fila/atribuição/tentativa e preserva unicidades por
ciclo. As FKs continuam nulas para compatibilidade de versão mista.

## Limite operacional

Este artefato não autoriza execução em banco compartilhado. Relatório real,
exceções e PostgreSQL 16 devem ser revisados no Gate F antes de autorização de
backfill em staging ou produção.
