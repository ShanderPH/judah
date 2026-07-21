# Research — reentrada de conversa encerrada como novo atendimento

**Request:** `hotfix/reopened-conversation-assignment`

**Data:** 21 de julho de 2026

**Fase:** RESEARCH — nenhuma correção foi implementada
**Incidente de origem:**
`ai-system/requests/hotfix/agent-absence-eligibility/00-context/executive-summary-duplicate-assignment-incident.md`

## 1. Decisão executiva

O comportamento correto não é impedir permanentemente uma nova atribuição para
um `ticket_id` que já foi concluído. Uma conversa encerrada que retorna ao estágio
NOVO inicia um **novo ciclo de atendimento** e deve poder ser atribuída novamente,
sem apagar ou reescrever o ciclo anterior.

O defeito é uma incompatibilidade entre o domínio e a identidade persistida:

- o domínio permite vários ciclos sequenciais para o mesmo ticket HubSpot;
- as tabelas operacionais e o protocolo durável tratam `ticket_id` como se ele
  identificasse um único atendimento durante toda a vida do ticket;
- por isso, a segunda alteração externa pode ocorrer, mas a conclusão local é
  bloqueada pela unicidade global de tentativa concluída.

A abordagem recomendada é introduzir uma identidade explícita e imutável de
**ciclo de atendimento**, pertencente ao domínio de suporte, e fazer fila,
atribuição, fechamento, reparo e métricas operarem por esse ciclo. A unicidade
deve continuar forte, mas mudar de “uma conclusão por ticket para sempre” para
“uma conclusão automática por ciclo”.

Este não é um ajuste seguro de uma única condição. Ele cruza modelos, migração,
ingestão, protocolo durável, fechamento, reparo e métricas. Conforme o
`AGENTS.md`, a mudança deve ser tratada como Ciclo F antes da implementação,
apesar da branch e da prioridade operacional continuarem sendo de hotfix.

## 2. Correção da premissa do incidente original

O resumo do incidente recomenda “adicionar um veto autoritativo de ticket
concluído”. Essa recomendação precisa ser refinada à luz da regra de negócio
confirmada nesta request:

> O veto deve impedir outra tentativa para o **mesmo ciclo**, não impedir um
> novo atendimento após fechamento e reentrada legítima na fila.

Portanto:

- uma repetição do mesmo webhook de entrada deve ser idempotente;
- dois workers não podem criar duas atribuições para a mesma entrada na fila;
- um ticket ainda ativo não pode abrir outro ciclo concorrente;
- uma nova entrada posterior ao encerramento deve criar outro ciclo;
- todos os ciclos anteriores devem permanecer auditáveis e contabilizáveis.

## 3. Escopo e não escopo deste research

### Incluído

- fluxo webhook HubSpot → persistência → Celery → fila → Matchmaker;
- protocolo durável reserve/apply/finalize/compensate/repair;
- fechamento e reentrada no estágio NOVO;
- constraints e identidade dos registros operacionais;
- isolamento de falhas no reparador;
- impacto em auditoria, métricas e migração de dados;
- práticas atuais de Django 5.2, PostgreSQL 16, Celery 5 e sistemas assíncronos.

### Não incluído nesta etapa

- alteração de código ou migrations;
- testes de execução ou acesso a banco não local;
- reconciliação manual dos tickets `46934213935` e `46889914778`;
- decisão sobre o proprietário definitivo de casos já divergentes;
- deploy, mudança de flags, commit, push ou PR.

## 4. Fontes internas analisadas

- `AGENTS.md`;
- resumo executivo do incidente de duplicidade;
- `apps/webhooks/api.py`, `models.py`, `services.py` e
  `handlers/hubspot_handler.py`;
- `apps/ai_agents/models.py` e `services/lifecycle.py`;
- `apps/support/models.py`, `tasks.py`, `matchmaker_service.py`,
  `durable_assignment_service.py` e `auto_assign_service.py`;
- migrations `0002`, `0004`, `0017`, `0018` e `0019` de `apps/support`;
- testes de lifecycle, Matchmaker, protocolo durável e rollout gate;
- documentação de arquitetura, banco, workflows e operação de atribuição.

## 5. Fluxo atual observado

```text
HubSpot: ticket entra em NOVO
  -> webhook ticket.propertyChange
  -> WebhookEvent é persistido
  -> lifecycle registra ticket_entered_n1 no ConversationInstance do ticket
  -> task_matchmaker_assign_single(ticket_id, entered_at_ms)
  -> enqueue_new_ticket usa get_or_create(ticket_id)
  -> reserve_next_assignment cria AssignmentAttempt(ticket_id)
  -> HubSpot owner é alterado
  -> finalize cria AssignedConversation e AssignmentLog
  -> ticket fecha
  -> AssignedConversation é movida para ClosedConversation(ticket_id)
  -> ticket retorna a NOVO
  -> nova fila/tentativa reutiliza o mesmo ticket_id
  -> a conclusão colide com uniq_completed_assignment_ticket
```

O `ConversationInstance` da camada de lifecycle já aceita a transição de um
estado terminal para `QUEUE_PENDING` em `ticket_entered_n1`. Porém ele é único
por ticket e é reaberto no mesmo registro. Ele funciona como agregado de vida do
ticket, não como identidade independente de cada atendimento. Usá-lo diretamente
como ciclo manteria a mesma ambiguidade.

## 6. Achados na codebase

### 6.1 Unicidades globais incompatíveis com reentrada

| Componente | Regra atual | Consequência na reentrada |
|---|---|---|
| `NewConversation` | `hubspot_ticket_id` único | só representa uma fila ativa por ticket; aceitável apenas se houver ciclo associado |
| `AssignedConversation` | `hubspot_ticket_id` único | só representa uma atribuição ativa; aceitável apenas se o histórico estiver separado por ciclo |
| `ClosedConversation` | `hubspot_ticket_id` único | impede guardar dois encerramentos do mesmo ticket |
| `AssignmentAttempt` | uma tentativa `completed` por `ticket_id` | bloqueia toda atribuição de ciclos posteriores |
| `ConversationInstance` | um registro por `hubspot_ticket_id` | registra reabertura como nova transição, não como novo atendimento |

`AssignmentLog` admite múltiplas linhas por ticket, mas não possui uma chave de
ciclo; logo, não consegue distinguir com autoridade reatribuições internas de
uma nova passagem completa pelo helpdesk.

### 6.2 A admissão muda conforme o entrypoint

`reserve_next_assignment(ticket_id)` consulta uma tentativa concluída quando o
ticket é informado. O drain FIFO chama `reserve_next_assignment()` sem ticket;
nesse caminho, a consulta antecipada não ocorre. Dentro da transação há veto a
tentativas em estados vivos, mas não a uma conclusão anterior. Isso explica a
hipótese do incidente, porém apenas adicionar a consulta ausente perpetuaria a
regra de domínio incorreta e bloquearia reaberturas legítimas.

A invariância precisa ficar dentro da transação e usar a chave do ciclo,
independentemente de o chamador selecionar uma linha específica ou a cabeça da
fila.

### 6.3 O fechamento perde histórico de ciclos posteriores

`handle_ticket_closed()` usa `ClosedConversation.get_or_create(ticket_id)` e
depois remove a linha ativa de `AssignedConversation`. Em uma segunda passagem,
o fechamento encontra o registro antigo e não cria um novo. Métricas de tempo de
fila, handle time, agente e horário de fechamento do segundo atendimento seriam
perdidas ou misturadas.

### 6.4 A origem já fornece um candidato a discriminador de ciclo

O webhook de entrada é disparado pela propriedade
`hs_v2_date_entered_<NOVO_STAGE_ID>` e envia o valor em `propertyValue`. O fluxo
já o encaminha como `entered_at_ms`. A reconciliação da fila também busca
`entered_novo_at`.

A documentação atual do HubSpot afirma que propriedades calculadas de estágio
continuam sendo atualizadas quando um ticket é fechado e reaberto. Assim, a
ocorrência de entrada no estágio, combinada com `ticket_id`, é o melhor candidato
externo disponível para deduplicar o mesmo evento e distinguir uma reentrada
posterior.

Há duas falhas atuais relacionadas:

- `get_ticket_details()` solicita propriedades de entrada nos estágios, mas não
  as devolve no dicionário normalizado;
- os entrypoints usam `timezone.now()` quando o timestamp falta. Esse fallback é
  inadequado para identidade: cada retry poderia inventar um ciclo diferente.

Timestamp ausente deve causar recuperação explícita do histórico/propriedade
atual no HubSpot ou adiamento fail-closed, nunca a geração silenciosa de uma
nova chave com o relógio local.

### 6.5 Webhook persistido não é idempotente no primeiro ledger

`WebhookEvent.event_id` é indexado, mas não único, e cada entrega cria uma nova
linha. A camada `ConversationEvent` possui `idempotency_key` único e deduplica
mais tarde. O protocolo de suporte não deve depender apenas do lock Redis de 30
segundos: o HubSpot pode reenviar falhas por até 24 horas, e locks temporários
não são uma chave de idempotência durável.

### 6.6 O reparador possui blast radius de lote

`repair_assignment_attempts()` itera o lote e chama finalize/retry/reconcile sem
isolar exceções por tentativa. Uma `IntegrityError` em um item interrompe todos
os seguintes. O incidente conhecido demonstrou esse comportamento.

O reparador deve tratar cada item como unidade independente, com transação ou
savepoint próprio, classificação durável do conflito, logging com `cycle_id` e
continuação do lote. Falhas inesperadas ainda devem ficar visíveis e provocar
alerta; “continuar” não pode significar engolir erro.

### 6.7 A operação HubSpot + PostgreSQL é uma saga

Não existe transação ACID única entre a alteração do owner no HubSpot e a
finalização local. O protocolo durável já implementa parte correta do padrão:
estado reservado, aplicação externa, finalização, compensação e reparo. O novo
ciclo deve estender esse protocolo, não substituí-lo nem mover a chamada externa
para dentro de uma longa transação de banco.

## 7. Invariantes de domínio propostos

1. Um ticket HubSpot pode possuir zero ou muitos ciclos históricos.
2. No máximo um ciclo pode estar ativo por ticket.
3. Uma ocorrência de entrada em NOVO cria no máximo um ciclo.
4. O mesmo webhook, retry ou backfill para a mesma ocorrência retorna o mesmo
   ciclo e não repete efeitos.
5. Um ticket só abre novo ciclo se o ciclo anterior estiver terminal ou se uma
   política explícita reconciliar a anomalia.
6. No máximo uma tentativa viva existe por ciclo.
7. No máximo uma tentativa concluída automática existe por ciclo.
8. Reatribuições dentro do mesmo atendimento permanecem no mesmo ciclo.
9. Cada fechamento terminal cria exatamente um registro histórico por ciclo.
10. Fila, atribuição, fechamento, logs, métricas e reparo carregam `cycle_id`.
11. Eventos antigos ou fora de ordem não podem reabrir nem fechar um ciclo mais
    novo.
12. Nenhuma chamada externa ocorre antes de a reserva e suas invariantes estarem
    confirmadas no PostgreSQL.

## 8. Abordagens avaliadas

### A. Apenas adicionar o veto de tentativa concluída ao drain

**Vantagem:** alteração pequena e impede o erro de constraint depois da chamada
externa.

**Problema decisivo:** trata reentrada legítima como duplicidade permanente.
Não atende ao requisito e deixa `ClosedConversation` sem múltiplos históricos.

**Conclusão:** rejeitada.

### B. Apagar, reabrir ou reciclar registros concluídos

Exemplos: remover a tentativa anterior, resetar seu estado, sobrescrever
`ClosedConversation` ou reutilizar o mesmo registro de atribuição.

**Vantagem:** preserva o schema atual.

**Problemas:** destrói auditoria, mistura SLAs e agentes de ciclos diferentes,
torna compensação ambígua e dificulta investigação de incidentes.

**Conclusão:** rejeitada.

### C. Adicionar somente um `cycle_key` desnormalizado às tabelas existentes

**Vantagem:** menor quantidade de entidades novas; constraints podem passar a
usar `(ticket_id, cycle_key)`.

**Problemas:** a definição de ativo/fechado fica duplicada entre várias tabelas;
não há um lugar autoritativo para serializar a abertura; backfill, auditoria e
reconciliação tornam-se mais frágeis.

**Conclusão:** viável como contenção, mas inferior para correção definitiva.

### D. Entidade de ciclo de atendimento + vínculos operacionais

Criar uma entidade de domínio no app `support` — nome sugerido
`SupportConversationCycle` — com:

- UUID interno;
- `hubspot_ticket_id`;
- chave de ocorrência externa imutável;
- timestamp de entrada no estágio;
- estado do ciclo (`queued`, `assigned`, `closed`, `cancelled`,
  `repair_required`);
- timestamps de abertura/encerramento;
- referência opcional ao evento de origem apenas para auditoria, sem tornar
  `support` dependente da execução da camada de AI lifecycle.

`NewConversation`, `AssignedConversation`, `ClosedConversation`,
`AssignmentAttempt`, `AssignmentLog` e, idealmente, `ConversationReassignment`
passam a referenciar o ciclo.

Constraints recomendadas:

- `cycle_key` único;
- unicidade de `(hubspot_ticket_id, entered_stage_at)` quando o timestamp for a
  fonte confirmada;
- índice único parcial em `hubspot_ticket_id` para estados ativos;
- uma tentativa viva por `cycle_id`;
- uma conclusão automática por `cycle_id`;
- um fechamento por `cycle_id`.

**Vantagens:** traduz o domínio diretamente, centraliza o estado, preserva
histórico, facilita métricas e torna as constraints corretas e legíveis.

**Custo:** migration e alteração transversal; exige rollout expand/contract e
testes PostgreSQL reais.

**Conclusão:** abordagem recomendada.

## 9. Forma recomendada da chave do ciclo

Prioridade de fontes:

1. `ticket_id + hs_v2_date_entered_<NOVO>` recebido no webhook;
2. a mesma propriedade atual confirmada por leitura do ticket;
3. histórico de `hs_pipeline_stage` via `propertiesWithHistory` para recuperar
   ou validar a ocorrência;
4. quarentena/adiamento quando não for possível provar a ocorrência.

A chave pode ser um hash ou texto normalizado de
`hubspot:<portal/contexto>:<ticket_id>:<entered_at_utc>`. O plano deve confirmar
se o portal precisa entrar na chave; hoje o repositório parece operar um único
portal, mas omitir essa decisão agora criaria risco futuro de colisão multi-tenant.

Não usar:

- horário de recebimento local;
- UUID aleatório novo a cada retry;
- `eventId` isoladamente como identidade do atendimento;
- owner atual;
- apenas `ticket_id`.

O `eventId` é apropriado para deduplicar a entrega. A entrada no estágio é a
identidade semântica do ciclo. São responsabilidades diferentes.

## 10. Fluxo alvo de alto nível

```text
ticket_entered_novo(ticket_id, entry_timestamp, source_event_id)
  -> validar estado atual no HubSpot e ausência de owner
  -> transaction.atomic
       -> obter/criar cycle pela chave externa
       -> lock no ciclo/ticket
       -> se mesma ocorrência: devolver resultado idempotente
       -> se outro ciclo ativo: classificar conflito, sem chamar HubSpot
       -> criar/obter fila vinculada ao cycle
  -> após commit, disparar processamento
  -> reservar agente sob lock por cycle_id
  -> aplicar owner no HubSpot
  -> finalizar localmente por cycle_id

ticket_closed(ticket_id, close_occurrence)
  -> localizar e travar o ciclo ativo compatível
  -> se fechamento antigo/duplicado: no-op auditável
  -> criar ClosedConversation para o cycle
  -> marcar cycle fechado e remover projeção ativa
```

O disparo Celery após uma criação transacional deve usar
`transaction.on_commit()` ou um outbox. Para o hotfix, `on_commit()` reduz o
risco de executar antes do commit, mas não elimina a janela “commit feito,
publish falhou”. Se essa janela já for material para o SLA, um outbox
transacional é a solução mais robusta; caso contrário, o reconciliador periódico
pode ser mantido como safety net documentado.

## 11. Reparo e reconciliação

O reparador deve:

- selecionar lote limitado em ordem determinística;
- processar cada tentativa em uma unidade transacional isolada;
- capturar e classificar erros esperados por item;
- incrementar contadores como `completed`, `retryable`, `repair_required`,
  `conflict`, `failed_unexpected` e `skipped_stale_cycle`;
- continuar para o item seguinte;
- preservar erro e contexto no registro da tentativa;
- emitir alerta agregado quando houver falhas, sem esconder o resultado parcial.

Para `external_applied` de incidentes antigos sem ciclo confiável, o reparador
não deve escolher silenciosamente qual histórico sobrescrever. Deve comparar o
owner externo, o log anterior e o ciclo reconstruído, então encaminhar a uma
política explícita de forward recovery, compensação ou revisão humana.

## 12. Migração e compatibilidade

Estratégia sugerida para o futuro plano:

1. **Expandir:** criar tabela de ciclos e FKs nulas, sem remover constraints
   antigas.
2. **Backfill determinístico:** criar um ciclo legado por atendimento que possa
   ser provado a partir de fila, atribuição, fechamento, tentativas e logs.
3. **Auditar exceções:** separar tickets com estados conflitantes ou múltiplas
   ocorrências não correlacionáveis; não inventar ciclos.
4. **Adicionar constraints novas:** validar uma por vez no PostgreSQL.
5. **Trocar writers/readers:** todos os entrypoints passam a usar `cycle_id`.
6. **Contrair:** remover unicidades globais incompatíveis somente depois de
   comprovar cobertura e ausência de writers antigos.

O trigger de isolamento de writers criado nas migrations anteriores também
deverá proteger a nova tabela e as novas colunas. A migration precisa de caminho
reverso e validação em PostgreSQL 16; SQLite não prova índices parciais, locks ou
triggers de produção.

## 13. Boas práticas atuais aplicáveis

### Django 5.2

- `transaction.atomic()` garante commit integral ou rollback do bloco;
- `select_for_update()` deve ser avaliado dentro de transação e manter o lock
  até seu término;
- `UniqueConstraint(condition=...)` expressa a unicidade parcial no modelo;
- `transaction.on_commit()` evita publicar trabalho referente a dados que ainda
  podem sofrer rollback.

Aplicação no JUDAH: a criação/deduplicação do ciclo e a reserva devem ser
atômicas; a chamada ao HubSpot permanece fora do lock longo e é convergida pelo
protocolo durável.

### PostgreSQL 16

- índices únicos parciais são adequados para “no máximo um registro ativo”;
- `FOR UPDATE SKIP LOCKED` é apropriado para consumidores concorrentes da fila;
- constraints do banco permanecem a última barreira contra corridas, mas devem
  representar a chave de negócio correta — aqui, o ciclo.

### Celery 5

- tarefas devem ser idempotentes antes de habilitar confirmação tardia;
- retries transitórios devem usar backoff e jitter;
- redelivery não é exactly-once e não substitui uma chave durável;
- um item venenoso deve ser isolado em vez de bloquear toda a fila ou lote.

### Sistemas distribuídos

- HubSpot + PostgreSQL formam uma operação distribuída com consistência
  eventual; reserve/apply/finalize/compensate é uma saga;
- consumers precisam tolerar entrega duplicada e eventos fora de ordem;
- uma chave de sequência/ocorrência deve acompanhar eventos cujo ordenamento é
  relevante;
- outbox transacional resolve o dual write banco + publicação, mas não elimina a
  necessidade de consumer idempotente.

## 14. Matriz mínima de testes para o plano

### Domínio e idempotência

- primeira entrada cria ciclo 1;
- retry do mesmo evento mantém ciclo 1 e uma única atribuição;
- fechamento encerra ciclo 1 e registra suas métricas;
- nova entrada posterior cria ciclo 2 e permite novo agente;
- segundo fechamento preserva ambos os históricos;
- três ou mais reentradas continuam válidas;
- reatribuição manual dentro do ciclo não cria novo ciclo.

### Concorrência PostgreSQL

- dois workers para a mesma ocorrência criam um ciclo e uma reserva;
- webhook e sync concorrentes convergem no mesmo ciclo;
- drain sem `ticket_id` respeita as mesmas constraints do caminho unitário;
- dois eventos de ciclos diferentes não ficam ativos ao mesmo tempo;
- evento antigo chegando depois do novo não regride o ciclo atual.

### Falhas distribuídas

- crash após aplicar owner e antes de finalizar converge no ciclo correto;
- retry de chamada externa não incrementa capacidade ou métricas duas vezes;
- conflito em uma tentativa não interrompe o restante do lote de reparo;
- owner externo divergente é classificado e não sobrescreve história
  silenciosamente.

### Migration e métricas

- backfill de pending, assigned, closed e completed preserva contagens;
- exceções do incidente ficam identificadas para reparo manual;
- métricas contam atendimentos/ciclos, não apenas tickets distintos;
- rollback da migration preserva dados ou é explicitamente bloqueado antes de
  qualquer etapa destrutiva.

## 15. Observabilidade e auditoria

Logs e métricas devem carregar pelo menos:

- `ticket_id`;
- `cycle_id` e `cycle_key` segura para log;
- `source_event_id`;
- `attempt_id`;
- estado anterior e novo;
- classificação de resultado externo e de reparo.

Métricas sugeridas:

- ciclos abertos, reabertos, fechados e em conflito;
- duplicatas idempotentes por fonte;
- ciclos ativos por ticket acima de 1 (deve ser zero);
- tentativas `external_applied` por idade;
- falhas por item e lotes parcialmente reparados;
- divergências owner externo × ciclo ativo.

## 16. Riscos e perguntas para o plano

1. Confirmar se `hs_v2_date_entered_<NOVO>` sempre muda em cada reentrada na
   assinatura/licença HubSpot usada em produção.
2. Confirmar o comportamento esperado do owner ao reabrir: o HubSpot o limpa
   automaticamente ou existe automação separada?
3. Definir se reentrada em NOVO enquanto ainda existe ciclo local ativo deve
   falhar, encerrar/superseder o anterior ou ir para revisão.
4. Definir retenção de tentativas concluídas. A purga atual em 30 dias pode
   remover parte da evidência necessária para auditoria de ciclos longos.
5. Confirmar se `ConversationReassignment` e dashboards externos precisam de
   `cycle_id` já no primeiro release ou em compatibilidade posterior.
6. Definir política formal para os casos legados já `external_applied`.
7. Medir volume para decidir entre FK/índices criados em uma migration ou
   rollout expand/contract em mais de um deploy.

## 17. Critérios para aprovar o futuro plano

O plano só deve avançar se:

- a identidade de ciclo e sua fonte externa estiverem explícitas;
- reentrada legítima e retry duplicado estiverem diferenciados;
- todas as constraints forem descritas por ciclo;
- o histórico de dois fechamentos do mesmo ticket for preservado;
- a migração dos dados atuais e dos incidentes divergentes estiver definida;
- o reparador isolar falhas por item;
- testes PostgreSQL de concorrência e migration forem obrigatórios;
- nenhuma mutação de produção ou reconciliação manual estiver embutida sem gate
  de aprovação separado.

## 18. Referências externas consultadas

Documentação consultada em 21 de julho de 2026:

- [Django 5.2 — Transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- [Django 5.2 — QuerySet `select_for_update`](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)
- [Django 5.2 — Model constraints](https://docs.djangoproject.com/en/5.2/ref/models/constraints/)
- [PostgreSQL 16 — Partial indexes](https://www.postgresql.org/docs/16/indexes-partial.html)
- [PostgreSQL 16 — Explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html)
- [Celery — Tasks, idempotency and retries](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Celery — Optimizing workers and acknowledgements](https://docs.celeryq.dev/en/stable/userguide/optimizing.html)
- [HubSpot CRM Tickets API 2026-03](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/tickets/guide)
- [HubSpot — Stage calculated properties](https://knowledge.hubspot.com/properties/stage-calculated-properties)
- [HubSpot — Webhooks API guide 2026-03](https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide)
- [HubSpot — Error handling and webhook retries](https://developers.hubspot.com/docs/api-reference/error-handling)
- [AWS — Transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
- [AWS — Saga patterns](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/saga-patterns.html)
- [Azure Well-Architected — Background jobs](https://learn.microsoft.com/en-us/azure/well-architected/design-guides/background-jobs)

## 19. Recomendação final

Prosseguir para planejamento com a abordagem **D: entidade explícita de ciclo de
atendimento**, usando a ocorrência de entrada no estágio NOVO como base de
idempotência semântica, constraints por ciclo e rollout expand/contract.

O plano deverá separar:

1. schema e backfill;
2. ingestão idempotente de ciclo;
3. adaptação do protocolo durável;
4. fechamento e histórico multi-ciclo;
5. reparo isolado e tratamento dos incidentes legados;
6. métricas/observabilidade;
7. verificação PostgreSQL e rollout.

Até a aprovação desse research e do futuro plano, nenhuma correção de código,
migration ou reconciliação de produção deve ser executada.
