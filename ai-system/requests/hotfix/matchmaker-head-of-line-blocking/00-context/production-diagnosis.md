# Diagnóstico de produção

- A API recebeu 18 eventos de entrada no estágio NOVO e despachou as tasks Celery.
- O Worker executou 42 drenos e encontrou quatro agentes elegíveis.
- Todas as 44 tentativas de escrita falharam para o mesmo ticket FIFO `46735280255` com HubSpot `404 resource not found`.
- O item continuou em `new_conversations`; cada dreno encerrou após a primeira falha e bloqueou os tickets seguintes.
- Eventos NOVO também tentaram transicionar instâncias terminais `IGNORED`/`CLOSED` para `QUEUE_PENDING` sem habilitar reabertura.

## Contrato externo validado

O HubSpot Python SDK expõe `NotFoundException`/`ApiException.status`. Erros 404 são permanentes para a tentativa corrente; 429 e 5xx são transitórios e devem usar backoff.
