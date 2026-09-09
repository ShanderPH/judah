# Research — atribuição manual e capacidade da autoatribuição

Data: 2026-09-07. Etapa: **Research concluída; Planning aguarda aprovação**.

Base analisada: checkout local `hotfix/stabilize-cohort-48154078600`, HEAD `7e6519c207226429829d2d793719b0682f181847`. Nenhuma branch criada e nenhum código alterado. Alterações e arquivos não rastreados preexistentes foram preservados. Este documento é o único artefato de research criado.

## 1. Resumo e grau de certeza

O JUDAH **contabiliza atribuições manuais em alguns caminhos**, mas a projeção operacional de owner/carga possui lacunas. O Matchmaker decide a capacidade usando `Agent.current_simultaneous_chats`; a verificação remota atual consulta disponibilidade do usuário, não sua quantidade de tickets. A função que deveria reconciliar a carga antes da atribuição existe, porém não é chamada pelo fluxo atual.

Foram identificados quatro mecanismos concretos no código que sustentam o sintoma:

1. Ticket manual sem `AssignedConversation` e sem fila local `pending/queued` não gera incremento pelo webhook.
2. Transferência de conversa já atribuída, sem owner anterior parseável, consulta o owner atual, mas conserva `prev_owner_int=None`; a comparação posterior com o owner local descarta a transferência.
3. Quando a autoatribuição detecta outro owner no HubSpot, compensa sua reserva e coloca a fila em `failed`; o webhook subsequente não consome filas nesse estado para materializar a atribuição manual.
4. A reconciliação de carga anterior à reserva, descrita em `sat_service.py`, está desconectada. A correção agregada efetivamente agendada é horária.

**Conclusão:** há causas de inconsistência demonstráveis por leitura do fluxo e cobertura parcial executada. Sem ticket de exemplo, payload real e histórico de execução, não é possível afirmar qual delas causou o incidente relatado, sua frequência ou quantos agentes foram afetados. Não houve consulta a produção, HubSpot remoto, banco remoto ou configuração implantada.

## 2. Escopo e método

Investigação iniciada pelo [README](../../README.md), seguida por [documentação de suporte](../services/support.md), [fluxos](../architecture/data-flow.md), [decisões arquiteturais](../architecture/decisions.md) e [operação de elegibilidade](../operations/absence-safe-assignment.md). As descrições foram confrontadas com implementação e testes.

As referências abaixo usam caminhos relativos ao repositório e linhas do checkout analisado. Não foi necessário consultar documentação de bibliotecas: esta investigação trata da lógica de negócio local. Documentos antigos apresentam divergências; por exemplo, o heartbeat consta como 20s em `docs/services/support.md`, enquanto o default atual é 30s. Configuração local declarada não é comprovação de configuração em produção.

## 3. Comportamento esperado sustentado pelas fontes

| Contrato | Evidência |
|---|---|
| Carga inclui tickets de suporte atribuídos ao owner e fora do estágio fechado, independentemente da origem manual/automática | `HubSpotClient.count_active_tickets_by_owner`, `apps/integrations/hubspot/client.py:686`: filtro por pipeline + owner + estágio diferente de fechado, sem filtro de origem |
| Manual na fila consome uma unidade; transferência libera a origem e ocupa o destino | `tasks.py:591–618,643–648`; `admin_api.py:445,526`; testes `TestHandleOwnerChange` |
| Autoatribuição deve excluir agentes na capacidade | `queue_service.py:31`, `eligibility_service.py:94`, reserva sob lock em `durable_assignment_service.py:333–366` |
| Owner já presente deve ser preservado | `execute_assignment_attempt`, `durable_assignment_service.py:610–622`; teste `test_pre_effect_manual_owner_converges_without_owner_patch` |
| Reconciliação deveria captar manuais perdidas antes de atribuir | Docstring e implementação de `sat_reconcile_agent_load`, `sat_service.py:704`; **intenção documentada, não conectada ao fluxo atual** |
| Fechamento libera o agente da projeção atribuída; quem executou o fechamento é metadado | `_do_handle_ticket_closed`, `auto_assign_service.py:278`; testes de fechamento |

A regra de evitar dois tickets consecutivos consulta **somente logs automáticos**, conforme `get_last_assigned_owner_id` (`queue_service.py:218`) e `test_ignores_manual_assignments`. Isso não significa que tickets manuais devam ser excluídos da carga. Alterar essa regra de distribuição seria uma decisão de produto separada.

Ainda requer definição na Planning: tratamento operacional de tickets sem ciclo/projeção local, owner desconhecido, remoção de owner e transferências manuais acima da capacidade. O fato de a ingestão registrar uma ação externa não equivale a autorizar ou bloquear essa ação na interface do HubSpot.

## 4. Fluxo técnico atual

### 4.1 Entrada e lifecycle

`POST /api/v1/webhooks/hubspot/` → `WebhookEvent` durável/idempotente → `process_webhook_event` (`apps/webhooks/services.py:77`) → registro/normalização de lifecycle → handler determinístico → task de suporte.

`_dispatch_hubspot_lifecycle` (`services.py:60`) encaminha também a rota `IGNORE` ao handler operacional; portanto, owner não precisa ser uma transição de triagem para ser processado. Eventos considerados antigos pelo lifecycle podem ter seus efeitos suprimidos (`services.py:148`), e erros na projeção de lifecycle têm fallback ao handler. Nenhum desses estados equivale a prova de incremento de carga.

`hubspot_handler.py:48–76,165–182` encaminha `ticket.propertyChange` / `hubspot_owner_id` para `task_handle_owner_change`. O payload é repassado; não há enriquecimento de `previousValue` nesse handler.

Os manifests locais `inchurch-sandbox/src/app/webhooks/sandbox-webhooks-hsmeta.json` e `Judah HubSpot Integration/src/app/webhooks/judah-webhooks-hsmeta.json` incluem a propriedade de owner. O segundo diretório já estava não rastreado. Esses arquivos não provam assinatura instalada, entrega nem saúde do worker em produção.

### 4.2 Manual pelo JUDAH

`admin_api.manual_assign` (`:445`) exige manager/admin e autoridade de escrita. Se já houver `AssignedConversation`, chama `_force_reassign_internal`; se não houver projeção pendente ou atribuída, rejeita a ação.

Para fila existente: `reserve_manual_assignment` (`durable_assignment_service.py:415`) verifica elegibilidade conforme flags, bloqueia fila/agente, incrementa carga e atualiza `last_assignment_at`, criando `AssignmentAttempt` manual. `execute_assignment_attempt` confirma a operação no HubSpot. `finalize_assignment_attempt` (`:651`) grava atribuição/log, incrementa `total_assignments` e elimina a fila **sem incrementar novamente a carga**. Falhas seguem compensação/reparo.

Transferência forçada (`admin_api.py:526`) grava intenção de transferência, chama o provider e depois atualiza owner, log e contadores. Usa duas transações separadas pela chamada externa; não utiliza a mesma reserva durável de capacidade do caminho de primeira atribuição. Isso merece avaliação de concorrência, sem presumir que o caminho manual inteiro esteja quebrado.

### 4.3 Manual diretamente no HubSpot

`task_handle_owner_change` (`tasks.py:414`) obtém o owner anterior de `previousValue` **ou `sourceId`**, usando `_safe_parse_owner_id`. Sem anterior parseável, compara o owner local com o evento e, quando diferentes, consulta o ticket remoto. Depois chama `_do_handle_owner_change` sob `OwnedCacheLock` por ticket/origem/destino.

O processamento interno (`tasks.py:506`) tem dois caminhos:

- Sem atribuição local e com fila `pending/queued`: resolve eventual tentativa viva; finaliza se já `external_applied` para o mesmo owner, ou compensa a reserva; cria `AssignedConversation` e `AssignmentLog(manual, hubspot_manual)`, incrementa agente conhecido, atualiza ciclo `queued → assigned` e exclui a fila.
- Com atribuição local cujo owner coincide com o anterior recebido: decrementa origem, incrementa destino, atualiza projeção e cria `ConversationReassignment`. Owner desconhecido pode ser persistido com `agent=None`, sem incremento de um agente local.

Se nenhum caminho se aplicar, registra `task_owner_change_stale_cycle` e retorna. O lock é liberado ao final: protege execução concorrente, não constitui um ledger permanente de eventos. A idempotência também depende da comparação da projeção e do ledger de entrada.

### 4.4 Autoatribuição / Matchmaker

Entrada NOVO → `task_matchmaker_assign_single` (`tasks.py:94`) → `enqueue_new_ticket` → processamento. Há também drain periódico (`tasks.py:219`; Beat a cada 60s), callbacks de disponibilidade e recuperação.

`enqueue_new_ticket` confirma pipeline, estágio quando informado e ausência de owner (`auto_assign_service._is_ticket_eligible`, `:150`). Abre/recupera `SupportConversationCycle` e persiste fila com identidade temporal. Um ticket que já possua owner é rejeitado nessa admissão: ela não é importação de tickets manuais.

`process_queue_item` → `reserve_next_assignment` (`durable_assignment_service.py:205`) → barreira de abertura quando aplicável → `_verify_candidates` → lock de fila/ciclo/agente → revalidação local → incremento/reserva → `AssignmentAttempt` → leitura do ticket no provider → atribuição/confirmação → finalização ou compensação.

`_verify_candidates` (`:122`) chama `sat_verify_agent_assignment_eligibility` quando enforcement está ligado. Esta consulta usuário/disponibilidade/ausências e calendário (`sat_service.py:637`), **não quantidade de tickets do owner**. Com enforcement desligado, essa consulta também não ocorre. A carga usada continua sendo a coluna local.

### 4.5 Capacidade, disponibilidade e ranking

- `Agent.current_simultaneous_chats` é um contador persistido (`models.py:66`), não um `COUNT(AssignedConversation)` calculado na decisão. Reservas ainda não finalizadas também o ocupam.
- Capacidade local: `current < max`. SQL de seleção usa `Coalesce(max,5)`; validação Python usa `max or 5`. Valor zero produziria semânticas diferentes; não há evidência de que seja usado neste incidente.
- Incrementos normais usam `F()+1` e atualizam `last_assignment_at`; decrementos usam piso zero (`queue_service.py:169–215`). Reserva durável incrementa sob lock e compensação libera uma vez.
- Seleção exige online, autoatribuição habilitada, agente não explicitamente inativo e capacidade. Enforcement acrescenta snapshot elegível/fresco; canário pode restringir candidatos (`queue_service.py:31`).
- Ranking: evita último owner **automático** quando há alternativas, ordena por `last_assignment_at`, depois carga e UUID (`get_ranked_eligible_agents`, `:89`). Não é simplesmente menor carga primeiro.
- SAT (`sat_service.py:322`) materializa presença remota, ausências, calendário e estabilização. Defaults: freshness 60s, estabilidade 30s, duas amostras, heartbeat 30s (`core/settings/base.py:236–248`). Ele não sincroniza carga no heartbeat atual. Estar online não prova possuir capacidade livre.
- `total_assignments`, logs e histórico de atendentes são métricas/histórico; não são a fonte consultada para capacidade simultânea.

### 4.6 Reconciliação, fechamento e modelos envolvidos

`sat_reconcile_agent_load` (`sat_service.py:704`) consulta o total remoto e conserva `max(local, remoto)` frente ao snapshot lido; erros preservam carga local. Pesquisa de referências no repositório encontrou definição, docs, allowlist e testes, **nenhum chamador operacional atual**.

`task_reconcile_agent_counts` (`tasks.py:826`) está agendada a cada hora em `:30` (`core/settings/base.py:302`), apenas com autoridade e dentro do horário comercial. Para agentes `is_active=True`, substitui a coluna pelo total remoto, para cima ou para baixo; erro `-1` é ignorado. Não reconstrói `AssignedConversation`, ciclo ou histórico de owner. A janela de inconsistência não tem limite garantido de uma hora: depende de horário, sucesso do provider e execução do Beat/worker.

`sync_all_agents_status_and_counts_optimized` (`agent_sync_service.py:138`) também pode substituir contadores, mas não foi encontrado chamador operacional atual na busca global. Não deve ser contado como proteção ativa.

Fechamento lê `AssignedConversation` sob lock e decrementa seu agente, não o owner informado no fechamento. Sem essa projeção, cria registro mínimo de fechamento sem liberar carga por owner. Logo, corrigir apenas o agregado remoto pode deixar fechamento e histórico inconsistentes.

Modelos centrais: `Agent`, `NewConversation` (`models.py:345`), `AssignedConversation` (`:462`), `AssignmentAttempt` (`:522`), `SupportConversationCycle` (`:276`), `AssignmentLog`, `ConversationReassignment`, `ClosedConversation`; para ingestão/lifecycle, `WebhookEvent`, `ConversationInstance` e eventos/transições; para auditoria, `ConversationInstanceAttendant` e decisões de disponibilidade. `Ticket` CRUD e métricas agregadas não alimentam diretamente o contador. Não foi encontrado signal de suporte que recalcule carga ao salvar essas projeções (`apps/support/apps.py` não registra signals); a manutenção relevante é explícita nos services/tasks.

## 5. Causas e hipóteses priorizadas

### A — Transferência sem anterior parseável: falha lógica confirmada

Exemplo por execução simbólica do código: local `AssignedConversation.owner=A`, evento com novo owner B e sem `previousValue/sourceId` parseável. A task consulta o ticket e confirma B, mas mantém `prev_owner_int=None`. Em `tasks.py:636`, `A != None` resulta em retorno. A continua ocupada e B não recebe incremento. Remoção de owner sem anterior parseável também retorna cedo se a leitura remota estiver sem owner (`:468`).

Não foi validado que os eventos reais do incidente tenham esse formato. `sourceId` é tratado como identidade anterior sem comprovação no repositório: se for numérico mas diferente de A, o mesmo guard pode descartar a atualização; se coincidir por acaso, pode induzir uma origem incorreta. O contrato real e payloads precisam ser confirmados antes de qualquer mudança.

### B — Atribuição antes da projeção local: lacuna confirmada

Sem `AssignedConversation` e sem fila elegível, `_do_handle_owner_change` não cria nem contabiliza atendimento. A admissão NOVO também rejeita owner presente. Portanto, atribuição manual anterior ao processamento assíncrono de NOVO, ticket preexistente ou ticket fora da fila local pode permanecer apenas no HubSpot até uma correção agregada. Não há teste integrado desse encadeamento.

### C — Detecção de owner externo coloca a projeção fora do alcance do webhook: lacuna confirmada

Se uma tentativa automática selecionou A e a leitura pré-efeito encontra B, `execute_assignment_attempt` compensa A com `quarantine=True` e retorna `converged_external_owner` (`durable_assignment_service.py:610–622`). A fila fica `failed`. A consulta do handler manual aceita apenas `pending/queued` (`tasks.py:553–557`). Assim, um evento de B processado **depois** dessa detecção não cria projeção nem incrementa B por esse caminho.

O teste `test_pre_effect_manual_owner_converges_without_owner_patch` confirma a compensação e o estado `failed`, mas não verifica a convergência posterior para B. O nome do resultado não significa que capacidade/ciclo manual convergiram; isso também diverge da orientação operacional de convergir como `hubspot_manual` (`docs/operations/absence-safe-assignment.md:271`).

### D — Ausência de reconciliação no Matchmaker: amplificador confirmado

O fluxo reserva sobre contador local sem chamar `sat_reconcile_agent_load`. Um agente com local 4, máximo 5 e cinco tickets remotos pode continuar elegível e receber outra reserva. A consulta de disponibilidade do usuário e o lock local não detectam, por si, o ticket manual omitido. A confirmação definitiva desse cenário ponta a ponta requer teste que mantenha seleção real e simule contagens divergentes.

### E — Concorrência e entrega: riscos sustentados, incidência não demonstrada

- Reconciliação horária lê remoto antes de gravar um valor absoluto. Reserva/incremento concorrente pode ser sobrescrito; mesmo um lock durante a escrita não torna o snapshot remoto anterior atual.
- Reconciliar primeiro o total remoto e depois consumir um webhook manual pode contabilizar duas vezes a mesma ocupação, pois não há vínculo por ticket no agregado.
- Transferência forçada e seu webhook podem disputar as duas transações, repetindo deltas ou revertendo projeção. A cobertura lida não prova essas intercalações.
- Eventos antigos podem ser suprimidos pelo lifecycle; falha de entrega, assinatura inativa, task esgotando retries ou autoridade incorreta também poderiam explicar lacunas, mas não foram constatadas em produção.

## 6. Impacto, edge cases e regressões a considerar

- **Subcontagem:** sobrecarga real, agente indevidamente elegível e desempate distorcido. **Sobrecontagem:** agente excluído da seleção, capacidade ociosa e fila maior.
- Transferência perdida afeta dois agentes; fechamento posterior pode decrementar a origem antiga e perpetuar erro no destino.
- Manual deve afetar `last_assignment_at` nos caminhos que já o atualizam; isso é distinto da regra do último log automático.
- Owner desconhecido, agente criado depois do evento, `is_active=None` versus `True`, agente inativo/fora do canário e atribuição externa a agente ausente precisam de semântica explícita.
- Tickets já fechados, mudança de pipeline/estágio, reabertura do mesmo ticket e eventos atrasados não podem recriar atendimento em ciclo encerrado. O handler de owner não recebe identidade de ciclo na assinatura interna e consulta por ticket; evitar presumir que seu guard cobre todas as reaberturas.
- Preservar reservas vivas, compensação única, resposta ambígua do provider, retry/reparo, proteção de owner existente e processamento FIFO sem bloquear a fila.
- Uma correção por contagem remota não pode simplesmente somar todas as reservas ao total: algumas já podem estar refletidas no HubSpot.
- Reutilizar o reconciliador isolado sem analisar concorrência também é arriscado: sua comparação parte do objeto recebido e a escrita é absoluta. Não há prova de que preserve incrementos concorrentes.
- `assignment_readiness.py:242` chama de `capacity_drift_agents` apenas a contagem local acima do máximo; não compara com HubSpot nem detecta subcontagem. Readiness verde não exclui este bug.
- Histórico de atendentes não é contador de simultaneidade. O caminho automático transiciona `QUEUE_PENDING → HUMAN_ASSIGNED`; o manual registra atendente sem chamar diretamente a mesma transição. Verificar efeitos de lifecycle sem ampliar o hotfix por pressuposição.

## 7. Testes: cobertura e lacunas

### Executados neste research

Python **3.14.4**, Django 5.2.15, banco **SQLite local** imposto explicitamente; runner oficial, integrações mockadas, sem banco remoto. Comando reproduzível em PowerShell:

```powershell
$env:JUDAH_TEST_DATABASE_URL='sqlite:///./.test.sqlite3'
$env:PYTEST_ADDOPTS='--no-cov apps/support/tests/test_ticket_lifecycle.py apps/support/tests/test_sat_matchmaker.py apps/support/tests/test_durable_assignment_protocol.py apps/support/tests/test_queue_service.py apps/support/tests/test_admin_api.py apps/webhooks/tests/test_hubspot_handler.py'
.venv\Scripts\python.exe run_tests_local.py
```

Resultado: **90 passed, 4 skipped, 6.89s**, exit code 0. Os quatro testes ignorados exigem locks reais PostgreSQL: dois workers no mesmo ticket, última vaga, compensação única e finalização única. Houve aviso de cache do pytest e aviso esperado de coverage desabilitada. Não foi medido percentual de cobertura nem validada concorrência PostgreSQL/Redis/Celery real. Nenhum teste novo foi escrito.

### O que a cobertura demonstra

| Arquivo / teste | Prova e limite |
|---|---|
| `test_ticket_lifecycle.py`, `TestHandleOwnerChange` | Transferência com `previousValue`, projeção atualizada, lock ocupado, no-op, inicial com fila e compensação de reserva para mesmo owner |
| `test_initial_manual_owner_consumes_queued_projection_idempotently` | Duas chamadas internas não duplicam incremento; contorna task externa, payload e lifecycle |
| `test_skips_when_no_previous_owner` | Projeção já tem o novo owner; não testa transferência A→B sem anterior |
| `TestHandleTicketClosed` | Libera agente atribuído, piso zero, duplicação e fechamento sem projeção |
| `test_sat_matchmaker.py`, `TestSATReconcileLoad` | Helper isolado corrige para cima e preserva local em erro; não prova sua chamada pelo Matchmaker |
| `test_sat_matchmaker.py`, patches com `create=True` | Criam `matchmaker_service.sat_reconcile_agent_load` mesmo ausente no módulo; testes podem passar sem executar reconciliação real |
| `TestMatchmakerRetryReconciliation` | Substitui `_verify_candidates` por lista pronta; comentário fala em reconciliar dois agentes, mas assertion exige uma chamada ao mock da seleção |
| `test_durable_assignment_protocol.py` | Reserva/finalização/compensação, rejeição manual do provider, owner externo e falhas ambíguas; quatro provas concorrentes não executadas no SQLite |
| `test_admin_api.py::test_manual_assignment_and_force_reassignment` | Fluxo administrativo com reserva/execução mockadas na parte manual; não demonstra contagem remota divergente |
| `test_queue_service.py` | Limite local, ranking, incrementos/decrementos e exclusão de manual na regra do último log automático |
| `test_hubspot_handler.py::test_owner_change_dispatches_preserved_owner_task` | Dispatch do evento; não prova projeção, contador ou provider |

Também foram localizados testes de sincronização em `test_agent_sync_service.py`, de elegibilidade em `test_absence_safe_eligibility.py`, de barreira em `test_opening_cohort_barrier.py` e de ciclos/migrations. Esses arquivos adicionais não foram executados neste recorte.

### Cenários não demonstrados pela cobertura analisada

1. Transferência A→B e remoção de owner sem `previousValue`, incluindo `sourceId` ausente, inválido ou representando outra identidade.
2. Atribuição manual sem qualquer projeção; manual antes do evento NOVO; owner em fila `failed` após `converged_external_owner`.
3. Fluxo real de seleção com carga local abaixo do máximo e carga remota no máximo; persistência correta e nenhuma nova atribuição indevida.
4. Webhook manual após reconciliação agregada, retry completo, eventos repetidos A→B→A→B, eventos fora de ordem e reabertura.
5. Reconciliação concorrente com reserva/compensação/fechamento, transferência administrativa concorrente com webhook e autoatribuição.
6. Owner desconhecido, ausência de agente, pipeline diferente, fechado e capacidade excedida por ação externa.
7. Após convergir uma manual, fechamento libera exatamente uma unidade do destino correto e mantém ciclo/histórico coerentes.

## 8. Questões para orientar Planning

- Confirmar qual interface produziu as manuais afetadas e obter um caso com sequência de payloads, eventos e owners; a prioridade entre A/B/C depende dessa evidência.
- Definir o contrato entre agregado remoto, projeção por ticket/ciclo e reservas em andamento, inclusive quando a projeção falta ou está em quarentena.
- Determinar quais eventos precisam de revalidação autoritativa e como distinguir evento atrasado, repetição e nova transferência legítima.
- Delimitar capacidade versus ranking, disponibilidade e métricas. Preservar as regras de ausência/calendário/estabilização e a barreira de abertura; não há evidência de que relaxá-las resolva o problema.
- Exigir evidência que atravesse a seleção real; os mocks atuais deixam a integração de carga sem proteção. Concorrência deve ser demonstrada em PostgreSQL local descartável quando autorizada a Implementation.
- Para confirmar incidência em produção, correlacionar `WebhookEvent`/lifecycle, `AssignmentAttempt.decision_snapshot`, logs de owner/compensação, fila/ciclo, atribuição atual e histórico remoto. Coluna atual isolada e ausência de fila não provam a ordem dos fatos.
- Considerar reparação de dados já inconsistentes como escopo separado da prevenção de novos erros; nenhuma reparação foi realizada ou autorizada neste research.

Este documento não define sequência de implementação, alteração de schema ou rollout. **Planning só começa após aprovação do usuário. Na futura Implementation, a primeira ação obrigatória será criar a branch adequada ao hotfix antes de alterar código.**
