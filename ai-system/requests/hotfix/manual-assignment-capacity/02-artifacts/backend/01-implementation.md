# Implementação local

## Capacidade e persistência

`SupportTicketOccupancy` mantém a identidade `(portal, ticket)` mesmo nos estados sem ocupação. `AgentCapacityReservation` vincula uma operação a exatamente uma tentativa ou intenção administrativa. O contador em enforcement é a cardinalidade da união de ocupações ativas e reservas mantidas por agente.

`capacity_revision` e `capacity_reconciled_at` são independentes da presença SAT. O guard exige reconciliação completa/fresca e verifica novamente a capacidade sob lock do agente. Metadata inválida, snapshot conflitante ou leitura incompleta bloqueiam novas reservas.

## Ordem dos locks

Prefixo: ocupação do ticket → ciclos ordenados → filas ordenadas → operação/projeção/reserva → agentes em UUID crescente. Reserva/finalização/compensação/retry usam esse prefixo em enforcement. Transferência administra intenção e reserva antes da chamada externa. Repair em enforcement não mantém transação durante o provider. Fechamento confirma o ticket antes de entrar na transação de lifecycle.

Uma leitura captura a revisão local, executa o provider sem locks, e aplica somente se a revisão persistida ainda coincide. O scan mantém um contador exato das revisões escritas por ele para detectar outro writer concorrente. Uma busca sem um ID local exige leitura desse ID; não reduz carga por ausência em Search.

## Auditoria dos writers

| Writer | Enforcement |
|---|---|
| Reserva automática/manual e retry | Reserva identificada; `+1` legado desabilitado |
| Finalização | Exige ocupação confirmada para o destino; não incrementa carga |
| Compensação | Libera reserva uma vez; ambiguidade mantém reserva e degrada agente |
| Owner webhook | Confirma ticket; owner anterior vem da projeção bloqueada |
| Transferência administrativa | Intenção durável e reserva; readback/webhook convergem na mesma identidade |
| Fechamento | Confirma estado atual; libera a identidade, sem decremento legado |
| Job horário, SAT load helper, sync otimizado | Delegam à reconciliação por IDs |
| Helpers genéricos de incremento/decremento | Recusam uso sem identidade em enforcement |
| Criação/sync de agente | Contador inicial zero e capacidade `uninitialized`; bootstrap antes de reservar |

## Compatibilidade

`off` conserva o writer legado. `shadow` observa sem sobrescrever seu contador; falha de observação não bloqueia o handler legado. `enforce` usa o novo contrato e motivos específicos de adiamento. A disponibilidade, o calendário e a barreira de abertura mantêm seus guards.

Tickets sem ciclo comprovável ocupam capacidade sem criar atendimento histórico. Entrada NOVO com timestamp comprovado usa `open_or_get_cycle()`. Remoção de owner conserva o ciclo `assigned`, remove a projeção corrente e registra transferência sem destino; não reabre fila por inferência.

## Limites verificáveis

Não há transação distribuída com o HubSpot. GET com revisão local ainda pode desconhecer uma ação externa que não chegou ao provider consultado. Search é descoberta eventual. O contrato preserva reservas e impede decisão quando a carga conhecida está cheia ou sua evidência está degradada; não promete bloquear ações manuais no HubSpot.

Documentação consultada via Context7: [paginação e limites do CRM Search](https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm). O orçamento por conta e o tempo real de refresh devem ser aprovados no gate de shadow.
