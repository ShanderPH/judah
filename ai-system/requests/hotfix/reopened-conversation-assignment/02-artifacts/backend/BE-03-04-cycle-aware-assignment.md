# BE-03/04 - atribuição durável por ciclo

Single, drain e manual derivam o ciclo da fila e o travam antes de reservar. As
tentativas vivas/concluídas, idempotency key e snapshot usam o ciclo. A mutação
HubSpot só ocorre para ciclo `queued`; finalize transiciona para `assigned`, e
compensate/retry/reconcile permanecem vinculados ao ciclo original.
