# Master plan — capacidade após atribuições manuais

**Decisão de execução:** o usuário autorizou executar este plano em 2026-09-07/08. O desenho de Ciclo F foi implementado localmente; progresso e verificação em `STATUS.md`. As referências abaixo a autorização futura documentam a proposta original, sem autorizar publicação ou operações remotas.

Base: HEAD `7e6519c207226429829d2d793719b0682f181847`, branch preexistente `hotfix/stabilize-cohort-48154078600`.
Research: [manual-assignment-auto-assignment-hotfix.md](../../../../../docs/research/manual-assignment-auto-assignment-hotfix.md).
Data local: 2026-09-07 (America/Sao_Paulo). Autor: Codex, tarefa `/root`.

## 1. Resultado pretendido

Uma atribuição manual confirmada deve ocupar capacidade uma única vez. Uma transferência deve liberar a origem e ocupar o destino; o fechamento deve liberar o atendimento correto. Autoatribuição, atribuição administrativa e retries devem usar a mesma visão de ocupação e reservas, preservando os vetos de disponibilidade, calendário e ciclo.

O resultado deve cobrir tanto tickets que já passaram pela fila local quanto tickets atribuídos antes da criação dessa projeção. Um owner externo observado pelo Matchmaker deve convergir para ocupação local mesmo que sua fila tenha sido colocada em `failed`.

Não se promete impedir uma ação manual realizada no HubSpot simultaneamente à decisão do JUDAH, nem conhecer instantaneamente uma ação cujo webhook ainda não chegou e que ainda não aparece na busca. A garantia proposta é: processar idempotentemente as observações disponíveis, preservar reservas locais e impedir nova atribuição quando a carga conhecida já atingiu o limite ou sua reconciliação está incompleta/degradada.

## 2. Classificação e autorização

O problema nasceu como Ciclo M. **Propõe-se promoção para Ciclo F**, mantendo o nome de hotfix, porque a solução completa modifica o contrato de contagem, introduz persistência de ocupação/reserva e alcança mais de cinco arquivos de domínio. Isso atende ao §9 do `AGENTS.md`: mudança arquitetural exige escalada ao Felipe e aprovação do master plan.

A autorização recebida permite concluir este plano. Não autoriza implementação, branch, migration executável, integração remota, recuperação de dados, publicação, merge, deploy ou ativação de configuração. A aprovação futura deve contemplar explicitamente esta proposta de desenho/Ciclo F; não tratar o research como autorização para refatorar.

**Primeira ação da futura Implementation:** criar `hotfix/manual-assignment-capacity` antes de editar qualquer código ou teste. A base será a base de integração do projeto confirmada nessa ocasião; não assumir que a branch atual é a base correta. Se houver colisão de nome, preservar a branch existente. Após criar a branch, verificar HEAD/status e preservar toda alteração alheia; não restaurar as exclusões preexistentes em `ai-system`.

## 3. Evidências que motivam o desenho

| Evidência do research | Consequência para a solução |
|---|---|
| `tasks.py:447–468,636`: anterior ausente não é recuperado da projeção; `sourceId` é usado como anterior | O evento solicita reconciliação; o owner anterior vem do estado local bloqueado e o atual de uma observação confirmada |
| `tasks.py:550–557`: somente fila `pending/queued` permite criar atribuição manual | Ocupação não pode depender da existência/status da fila |
| `durable_assignment_service.py:610–622`: owner externo compensa e deixa fila `failed` | Convergência de owner e capacidade precisa ser parte explícita desse resultado |
| `_verify_candidates` não chama reconciliador de carga | Todos os caminhos de reserva precisam passar pelo mesmo contrato de capacidade |
| Reconciliador horário substitui o contador pelo total remoto | Eliminar mistura de totais absolutos com deltas de eventos |
| `AssignedConversation` depende de ciclo de atendimento e exige owner não nulo | Não inventar ciclo, timestamp de entrada ou atendimento atribuído para representar owner removido ou ticket sem identidade de ciclo |
| `compensate_assignment_attempt` pode liberar capacidade e manter estado `retryable/repair_required` | `LIVE_STATES` não equivale ao conjunto de reservas que ainda ocupam capacidade |
| API de transferência tem duas transações em torno do provider | Contador e webhook devem convergir pela mesma identidade; reserva de destino deve sobreviver a falha entre as etapas |

### Confirmação documental complementar

Consulta via Context7 às fontes oficiais do HubSpot durante Planning:

- Eventos podem chegar fora de ordem e duplicados. Usar identidade e `occurredAt` como evidência temporal, sem presumir ordem de entrega. [Webhooks guide](https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide).
- Os exemplos consultados não garantem `previousValue`; um exemplo oficial apresenta `sourceId=userId:...` em alteração de propriedade de contato. Isso não demonstra que esse campo seja o owner anterior de um ticket. A solução não dependerá dessa equivalência. [Exemplo de payload](https://developers.hubspot.com/docs/api-reference/latest/crm/properties/sensitive-data).
- Search tem atraso para refletir alterações, exclui arquivados e possui limites de requisições/resultados. Não é um snapshot transacional. [Limites de Search](https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm).
- A listagem paginada retorna IDs e `paging.next.after`; sua completude precisa ser verificada. [Tickets Search](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/tickets/search/search-tickets).

Nenhum contrato de API foi exercitado contra a conta real. Interface utilizada, ticket afetado e frequência do incidente continuam sem confirmação. Foi solicitada essa informação ao usuário; ela melhora a reprodução do incidente, mas os defeitos locais já sustentam os testes propostos.

## 4. Alternativas avaliadas

| Alternativa | Decisão |
|---|---|
| Corrigir somente `previousValue/sourceId` | Insuficiente: resolve parte das transferências, não resolve tickets sem fila, quarentena e reconciliação absoluta |
| Reativar `sat_reconcile_agent_load` antes da reserva | Insuficiente isoladamente: sincronização de agregado seguida de webhook pode duplicar contagem; snapshot antigo pode sobrescrever incremento |
| Aumentar frequência do job horário | Não corrige identidade/idempotência e aumenta a exposição às corridas |
| Usar apenas `COUNT(AssignedConversation)` | Não inclui tickets sem ciclo/projeção nem reservas em andamento |
| Usar apenas Search ou `max(total_local,total_remoto)` | Totais não identificam sobreposição; dois conjuntos diferentes de tamanho 4 podem representar 5 tickets |
| **Ocupação identificada por ticket + reserva explícita, com projeção do agregado** | **Recomendada:** permite deduplicar observação remota, evento e efeito automático, sem fabricar lifecycle |

Se for desejada uma mitigação cirúrgica anterior, ela precisará de escopo/aprovação próprios e não poderá ser apresentada como correção completa deste plano.

## 5. Contrato proposto

### 5.1 Fonte de capacidade e fórmula

Separar atendimento histórico de ocupação atual. Para um agente `a`:

```text
O(a) = IDs de tickets com ocupação ativa confirmada para a
R(a) = IDs de tickets com reserva de capacidade ainda mantida para a
C(a) = cardinalidade de O(a) união R(a)
```

O ID é composto por conta/portal + ticket. A deduplicação de capacidade é por ticket atual; a identidade de atendimento/histórico continua sendo o ciclo. Em uma transferência pendente, a origem pode manter ocupação e o destino uma reserva até a confirmação; cada agente conta esse ticket no máximo uma vez.

`Agent.current_simultaneous_chats` passa a ser a projeção materializada de `C(a)` em modo novo. Nenhum writer poderá simultaneamente aplicar `+1/-1` legado e rematerializar a mesma transição. `total_assignments`, métricas de duração e regra do último owner automático não mudam de significado.

### 5.2 Persistência proposta (nomes a estabilizar na revisão)

**`SupportTicketOccupancy`**, uma linha por `(source_account_id, hubspot_ticket_id)`:

- owner remoto atual, `agent` opcional, pipeline, estado `active/unassigned/closed/out_of_scope/unknown`;
- `cycle` opcional, sem gerar ciclo apenas para contar;
- instante de observação, instante/revisão de alteração fornecida pelo provider quando disponível, revisão local monotônica e origem da confirmação;
- identificação do evento/observação para auditoria, sem payload completo ou PII;
- linha conservada nos estados sem ocupação para rejeitar observações antigas e permitir serialização por ticket.

**`AgentCapacityReservation`**, reserva durável por operação:

- chave idempotente única da operação, ticket/conta, agente de destino;
- vínculo à `AssignmentAttempt` ou à `ConversationReassignment` que originou a operação;
- estado explícito `held/converted/released`, timestamps e motivo de conclusão;
- relação obrigatória com exatamente uma operação de origem; não usar expiração de lease como prova automática de que o efeito remoto não ocorreu.

**Metadados no agente:** revisão de capacidade e estado/instante de reconciliação (`uninitialized/ready/degraded`). `capacity_revision` não reutiliza `availability_revision`: presença e carga são evidências diferentes.

Constraints: unicidade por conta/ticket, unicidade da reserva por operação, exclusividade do vínculo de origem e consistência de estado/timestamps. Índices devem servir às consultas por agente/ocupação ativa, reserva mantida e revisões pendentes; justificar cada índice na migration. Não criar segunda restrição de atendimento que conflite com unicidade de `cycle` existente.

Migration aditiva e reversível em banco local descartável; número definido a partir da base atualizada. Seguir Django migrations e proteção de writer/RLS/grants do repositório, sem introduzir fluxo paralelo de migrations Supabase CLI. Tabelas operacionais não devem receber grants públicos `anon/authenticated` por conveniência.

### 5.3 Reconciliação por ticket

Criar um service compartilhado para webhook, detecção de owner externo, fechamento e confirmação administrativa:

1. Identificar ticket/conta e capturar revisão local antes da leitura remota.
2. Ler propriedades necessárias fora da transação: owner atual, pipeline, estágio, timestamps pertinentes e identidade do ciclo quando comprovável. Distinguir 404, arquivamento confirmado e erro transitório; um 404 isolado não é prova de fechamento e exige classificação conservadora.
3. Bloquear a linha de ocupação, comparar revisão e evidência temporal. Se outro writer avançou durante a leitura, descartar o snapshot e reagendar leitura limitada; não reaproveitar silenciosamente dados anteriores.
4. Determinar ocupação antiga pelo registro bloqueado, aplicar estado confirmado e resolver reserva relacionada. Atualizar projeções de atendimento quando houver ciclo comprovado.
5. Bloquear agentes afetados em ordem estável, rematerializar seus contadores e incrementar a revisão. Auditoria e agendamento de recheck devem ocorrer de forma idempotente, com dispatch após commit.

`previousValue` pode auxiliar auditoria, mas não define o débito. `sourceId` permanece metadado da origem. O evento não deve provocar incremento isolado antes de revalidar o estado do ticket.

Revisão local protege concorrência local; não prova consistência forte do provider. Não descartar informação local mais recente devido a Search. Divergência não resolvida marca os agentes afetados como degradados para novas reservas e gera recheck limitado.

### 5.4 Casos de owner e lifecycle

| Situação confirmada | Ocupação / atendimento |
|---|---|
| Inicial manual com fila/ciclo válido | Upsert da ocupação; atribuição/log manual uma vez; transição do ciclo e consumo da fila |
| Manual sem fila, mas com entrada NOVO comprovada | Ocupação imediata; criar/recuperar ciclo somente pelo contrato existente e materializar atendimento sem disparar autoatribuição |
| Manual sem identidade de ciclo comprovável | Contabilizar por ticket; manter ciclo ausente e diagnóstico; não inventar `entered_queue_at`, espera ou horário de atribuição histórico |
| Fila `failed` por `hubspot_manual_owner_observed` | Convergência específica após confirmar ticket/ciclo; não reabrir genericamente todas as filas com falha |
| Transferência A→B | Mudar ocupação e atualizar atribuição do ciclo válido; liberar A e ocupar B uma vez |
| Owner removido | Estado `unassigned`, nenhuma ocupação nem owner nulo em `AssignedConversation`; remover/encerrar a projeção corrente conforme contrato de ciclo. Reentrada na fila só com admissão/estado de ciclo válidos, nunca automática por inferência |
| Owner não cadastrado | Guardar owner com agente ausente; não criar agente automaticamente. Quando a identidade for cadastrada, reconciliar antes de torná-lo pronto |
| Owner ausente/inativo/acima do limite por ação externa | Registrar a realidade externa; não desfazer a ação. Impedir novas atribuições pelo JUDAH conforme capacidade/elegibilidade |
| Fechado/arquivado/fora do pipeline | Liberar ocupação após confirmação; fechar/cancelar atendimento apenas conforme contrato de lifecycle, sem falsificar resolução |
| Reabertura ou evento antigo | Atualizar capacidade do ticket atual; preservar identidade/histórico dos ciclos; snapshot antigo não pode restaurar owner/ocupação superados |

Para remoção de owner em ciclo `assigned`, o contrato atual não autoriza `assigned→queued`. Esta proposta preserva o ciclo e registra necessidade de reconciliação, liberando a ocupação; redefinir a máquina de estados/reentrada automática é uma mudança de produto fora deste hotfix.

### 5.5 Reserva e efeito externo

Autoatribuição inicial, manual na fila, retry e transferência administrativa deverão usar reserva explícita de destino antes do efeito remoto. Para transferências, vincular a reserva à intenção `ConversationReassignment` existente; não forçar uma segunda `AssignmentAttempt.COMPLETED` no mesmo ciclo, que violaria constraints atuais.

- Adquirir uma reserva exige agente pronto, capacidade disponível e elegibilidade atual, sob lock.
- Confirmação de owner converte reserva em ocupação na mesma transação lógica, sem aumentar a união duas vezes.
- Rejeição sem efeito libera reserva; timeout/resultado ambíguo mantém reserva até leitura conclusiva, ou bloqueia capacidade como degradada. Não liberar vaga apenas porque uma tentativa entrou em reparo.
- Retry só reserva novamente se a reserva anterior estiver efetivamente liberada. Repetição de finalização/compensação não altera contagem.
- Owner diferente observado antes do PATCH deve convergir sem sobrescrevê-lo. Owner diferente após chamada ambígua exige classificação/reconciliação; não presumir qual operação venceu.
- Workers distintos e callbacks do próprio PATCH usam a mesma linha de ocupação e a mesma reserva por operação.

### 5.6 Sincronização da carga remota

Substituir a escrita absoluta de totais por descoberta/reconciliação de **IDs de tickets**. O cliente adicionará método paginado e tipado de tickets ativos por owner, com status de completude. Reutilizar limites, timeouts e tratamento de erro do provider; não executar chamadas dentro de locks de banco.

- Search descobre tickets que não têm projeção local; cada alteração relevante é confirmada por leitura do ticket antes de mudar ocupação.
- Ausência em Search não fecha/remove ocupação: verificar por ID os registros locais ausentes da listagem.
- Resultado parcial, erro, limite excedido ou dúvida temporal não pode diminuir contagem nem marcar reconciliação como completa.
- Ao descobrir evento/owner novo durante um scan, comparar revisões antes de aplicar; a geração antiga não sobrescreve confirmação mais recente.
- O job horário, o helper antigo e qualquer writer de carga encontrado devem delegar ao contrato novo quando em enforcement. Não manter um writer legado de totais habilitado no mesmo agente.
- Refresh da capacidade é compartilhado por agente, com lock/lease e orçamento, evitando varrer toda a carteira para cada item do drain. Proposta inicial: evidência de reconciliação de até 60s, com invalidação em erro/conflito; configurar apenas após validar orçamento de chamadas. Uma primeira atribuição após bootstrap exige reconciliação completa.
- Snapshot expirado ou incompleto: adiar candidato com motivo específico e recheck, permitindo continuar para outros candidatos prontos. Todos os entrypoints, inclusive retry e admin, passam por esse guard.

O limite documentado de Search é compartilhado pela conta. A implementação deve respeitar esse orçamento e considerar outros consumidores. Frequência nominal não é SLO garantido. Gate de desempenho reprova o desenho se o refresh necessário exceder o orçamento; nesse caso, revisar o plano antes de ativar.

### 5.7 Concorrência e ordem dos locks

Proposta de ordem única para writers: ocupação por ticket → ciclo → fila → operação/reserva → agentes ordenados por ID. A seleção pode identificar uma fila candidata antes, mas deve revalidá-la depois de entrar nessa ordem; não manter um lock de fila enquanto tenta adquirir ocupação no sentido inverso.

Nenhum writer poderá adquirir agentes antes de buscar ciclo/fila/ocupação depois. Scans reconciliam um ticket por transação; processamento de múltiplos tickets não mantém locks acumulados. Criação concorrente da primeira ocupação usa unicidade e releitura segura, inclusive quando ainda não existe linha para bloquear.

A ordem precisa ser aplicada também a fechamento, compensação, retry, admin e finalização; não basta aplicá-la ao service novo. A prova será feita com PostgreSQL e barreiras determinísticas de concorrência. Redis ajuda a reduzir trabalho duplicado, mas a correção final depende das transações/constraints.

## 6. Plano de execução futuro e dependências

Todas as tarefas abaixo permanecem **não iniciadas**.

| ID | Trabalho | Dependência / evidência de saída |
|---|---|---|
| OPS-00 | Criar branch do hotfix como primeira ação da Implementation; confirmar base, SHA e drift | Aprovação deste plano/Ciclo F; branch identificada sem alteração alheia |
| V-01 | Escrever reproduções vermelhas de A/B/C/D do research com seleção real e provider simulado | OPS-00; falhas esperadas antes da correção, sem patch de `_verify_candidates` |
| DB-01 | Modelos de ocupação/reserva e metadados de capacidade; migration aditiva e reversível, writer guards | V-01; testes de constraints/migration local e enumeração da ordem de locks |
| BE-01 | Núcleo de ocupação, reserva, projeção de contador, revisão e classificação de divergências | DB-01; idempotência e união por ticket comprovadas |
| BE-02 | Reconciliação de owner por webhook e convergência de fila com owner externo | BE-01; transferências sem anterior, inicial sem fila e fila `failed` verdes |
| BE-03 | Integrar reserva/finalização/retry/compensação e transferência administrativa | BE-01/02; todos os efeitos têm reserva única e readback conclusivo |
| BE-04 | Integrar fechamento e projeções de ciclo/atendentes | BE-02/03; liberação exata e ciclos antigos preservados |
| INT-01 | Listagem remota paginada, completude e reconciliação por IDs com orçamento | BE-01; paginação, lag, erro e scan interrompido testados |
| BE-05 | Guard de capacidade compartilhado; substituir writers absolutos; bootstrap/shadow/enforcement | BE-03/04, INT-01; nenhuma rota bypassa capacidade nem mistura writers |
| OBS-01 | Motivos/telemetria, readiness de completude e consistência, documentação de semântica | BE-05; diagnosticar carga stale, desconhecida ou divergente sem PII |
| V-02 | Completar matriz funcional e gates PostgreSQL/Redis/Celery local | Todas BE/DB/INT; invariantes e fluxos reais verdes |
| V-03 | Ruff/mypy/suíte completa, auditoria de writers, revisão de riscos e HANDOFF | V-02; evidências em `03-verification/`; falhas baseline discriminadas |
| OPS-01 | Preparar runbook revisável de release/ativação/rollback e recuperação separada | V-03; não executar ações externas |

Não haverá subagentes nem branches paralelas para esta etapa; implementação pode ser serial para evitar concorrência nos mesmos writers. Criar `HANDOFF.md` antes de iniciar VERIFY, conforme AGENTS, com arquivos, comandos locais, riscos e pontos prioritários.

### Watch list / arquivos previstos

- Novos: `apps/support/capacity_service.py`, `apps/support/owner_reconciliation_service.py`, testes de capacidade/reconciliação e migration numerada na implementação.
- Persistência/protocolo: `apps/support/models.py`, `durable_assignment_service.py`, `queue_service.py`.
- Writers: `tasks.py`, `admin_api.py`, `auto_assign_service.py`, `sat_service.py`, `agent_sync_service.py`.
- Integração: `apps/integrations/hubspot/client.py`; handler de webhook apenas se necessário para transportar identidade temporal já disponível; nenhuma alteração em HMAC.
- Integração/diagnóstico: `matchmaker_service.py`, `assignment_readiness.py`, `error_catalog.py`, `availability_runtime.py`, `core/settings/base.py`, testes e documentação correspondentes.
- Revisar serializers/API de agentes apenas para manter a semântica do contador e expor prontidão se necessário; não incluir redesign de UI.

Mudanças além desses domínios, alteração de máquina de estados de ciclo, novo mecanismo de atribuição do HubSpot ou remoção das proteções de disponibilidade exigem revisão do plano.

## 7. Critérios de aceitação e matriz de validação

| Critério | Cenários mínimos | Evidência exigida |
|---|---|---|
| AC-01 — Manual única | Sem anterior, `sourceId` de ator, anterior incorreto, mesma entrega repetida | Uma ocupação; contador muda uma vez; task e handler reais |
| AC-02 — Transferência | A→B, A→B→A→B, remoção de owner, owner desconhecido | Origem/destino corretos; eventos antigos não desfazem estado atual |
| AC-03 — Sem fila | Manual antes de NOVO, sem timestamp de ciclo, fora de NOVO mas suporte aberto | Conta capacidade sem fabricar ciclo ou métricas de espera |
| AC-04 — Owner externo | Evento antes/depois de `converged_external_owner`; fila `failed` específica; outro erro permanente | Convergência manual; nenhuma reativação genérica ou PATCH indevido |
| AC-05 — Capacidade real | Local 4/remoto 5/máximo 5; conjuntos diferentes com mesma cardinalidade; dois candidatos | Nenhuma reserva para agente cheio; candidato alternativo processado |
| AC-06 — Não duplicar | Scan primeiro/webhook depois; webhook primeiro/scan depois; reserva refletida no provider | Uma unidade por ticket/agente; nenhum total absoluto sobrescreve mudanças |
| AC-07 — Efeito durável | Timeout após sucesso, rejeição antes do efeito, crash após PATCH, retry e compensação repetida | Reserva conservada/concluída uma vez; estado ambíguo não libera vaga insegura |
| AC-08 — Fechamento/ciclo | Fechar após transferência, fechar manual sem ciclo, reabrir ticket, fechamento antigo | Liberação correta; atendimento antigo não ressuscita |
| AC-09 — Concorrência PostgreSQL | Última vaga disputada; manual vs auto; admin vs webhook; scan vs fechamento/reserva; criação simultânea da ocupação | Threads/processos e barreiras reais; ausência de incremento perdido, duplicação e deadlock |
| AC-10 — Bootstrap e provider | Scan parcial, repetido, paginação, 429/timeout/5xx, lag, registros ausentes/arquivados | Não marcar pronto nem reduzir por ausência não confirmada; recheck limitado |
| AC-11 — Regressão | Manual, single, drain, retry, canário, off-hours, away, estabilidade, barreira e falhas de item | Mesmo contrato de elegibilidade; fila progride sem head-of-line blocking |
| AC-12 — Compatibilidade | `off`, `shadow`, `enforce`, reinício, migration forward/reverse/forward local | Modos não misturam contadores; shadow não muda decisão/owner do fluxo ativo |
| AC-13 — Qualidade/operação | Lint, tipos, testes, readiness e inspeção de writers | Nenhum writer de carga fora do contrato; docs e runbook consistentes |

Não aceitar testes que criam por `create=True` uma função inexistente, substituem toda a seleção de candidatos ou afirmam reconciliação apenas pelo nome do teste. Mockar fronteiras HTTP e controlar relógios de teste, preservando fluxo de domínio.

### Ambientes e comandos

- Baseline do research: **90 passed, 4 skipped**, SQLite. Não é execução desta etapa nem prova de concorrência.
- V-01 funcional: runner oficial com `JUDAH_TEST_DATABASE_URL=sqlite:///./.test.sqlite3`, seleção por `PYTEST_ADDOPTS` como no research; incluir testes novos após sua criação.
- V-02: PostgreSQL 16 local descartável, banco `judah_test` ou nome permitido `judah_ci_*`, validado por `common.database_safety`; Redis local isolado e worker Celery real para retries/dispatch. Credenciais apenas no ambiente. Comando-base: `.venv\Scripts\python.exe run_tests_local.py`; o relatório deve registrar a identidade redigida do banco e comandos exatos de infraestrutura escolhidos na implementação.
- V-03: `.venv\Scripts\ruff.exe check apps core common`, `.venv\Scripts\mypy.exe apps core common`; remover a seleção de `PYTEST_ADDOPTS` e rodar `.venv\Scripts\python.exe run_tests_local.py` para a suíte completa/coverage configurada. Funções novas tipadas; não reduzir a configuração para ocultar falhas.
- Inspecionar statements/planos das queries principais em dados locais representativos, locks e orçamento de provider. Não declarar desempenho validado por teste unitário mockado.
- Nenhum teste pode conectar a banco remoto; não usar o `conftest.py` contra produção. Testes PostgreSQL ignorados precisam rodar no gate local apropriado antes de VERIFY concluir.

## 8. Bootstrap, release e rollback propostos

### 8.1 Compatibilidade e modos

Proposta de modo `off/shadow/enforce`, default `off`, dedicado à capacidade nova. A interface exata deve ficar centralizada no runtime e ser testada; não alterar `AUTO_ASSIGNMENT_ENABLED` ou flags existentes agora. Em shadow, prontidão/revisões novas não poderão contaminar os guards legados; a contagem comparativa pode ser derivada das tabelas novas sem nova coluna pública de contador.

- **Off:** contrato antigo ativo, tabelas aditivas sem assumir prontidão.
- **Shadow:** registrar e comparar a projeção nova em colunas/tabelas próprias; não sobrescrever `current_simultaneous_chats`, não adquirir reserva extra com efeito nem mudar decisão legada. Comparação de decisão deve ser identificada como shadow.
- **Enforce:** todos os writers de carga usam o novo contrato; candidato exige bootstrap completo/fresco e nenhuma ambiguidade bloqueante.

Bootstrap deve importar evidências por ticket de projeções existentes, confirmar carteira remota e classificar reservas em andamento por estado **e prova de liberação/efeito**, não somente `LIVE_STATES`. Mismatch de ciclo ou owner permanece diagnosticado; não apagar históricos nem reatribuir tickets para ajustar números. Uma carteira remota sem ciclo ainda pode tornar capacidade conhecida, mantendo a dívida de lifecycle explícita.

Migração de esquema não executa backfill remoto. Bootstrap é operação idempotente separada, com relatório de diferenças e autorização de ativação. Incidência histórica do bug continua uma investigação separada.

### 8.2 Gates externos (não executados por este plano)

1. Aprovar publicação/release após testes locais e revisão. Preparar migration, compatibilidade e rollback concretos.
2. Validar em staging autorizado: API, worker, Beat no mesmo SHA; migrations e runtime role/RLS; smoke de atribuição/transferência/fechamento e logs. Testes destrutivos continuam exclusivamente locais.
3. Deploy aditivo com modo `off`; verificar esquema e serviços. Em releases com migration, respeitar a ordem operacional do repositório: API/predeploy primeiro, depois worker/Beat.
4. Autorizar shadow/ bootstrap e observar manual inicial, transferência, autoatribuição e fechamento representativos. Ausência de tráfego representativo não libera o gate.
5. Para enforcement, usar janela coordenada: suspender novas decisões automáticas e writes administrativos, manter ingestão durável, drenar ou classificar trabalho antigo e garantir nenhum consumidor com modo antigo escrevendo contadores. Só então promover projeção pronta e iniciar consumidores novos. Registrar último evento/generation processados; retomar pendências de forma idempotente.
6. Verificar capacidade, reservas, owners e histórico reais, além de readiness. Acompanhamento deve incluir pelo menos um ciclo de reconciliação e os cenários representativos; sem prazo artificial que substitua essa evidência.

Uma variável atualizada serviço a serviço não constitui corte atômico entre os dois contratos. Se não for possível uma janela de quiescência dos writers com ingestão preservada, retornar à revisão de desenho de ativação; não operar modos misturados.

### 8.3 Rollback

Antes da ativação, validar rollback em ambiente local/staging autorizado. Em regressão, suspender novas reservas mantendo ingestão. Classificar reservas ambíguas antes de voltar ao contrato anterior; não liberar capacidade nem reatribuir owner automaticamente para tornar contadores convenientes.

Reverter apenas código/modo pode deixar contadores semanticamente diferentes. O runbook deve preparar relatório e reconstrução compatível para os agentes afetados sob autorização própria. Conservar as tabelas novas para auditoria durante rollback de aplicação; reverse migration destrutiva serve à prova local e não será executada em produção como rotina.

Gatilhos de interrupção: dupla contabilização, capacidade conhecida excedida por decisão JUDAH, perda de reserva, eventos represados sem recuperação, loop de recheck, deadlock, orçamento do provider excedido ou divergência de owner após convergência.

## 9. Fora do escopo e incertezas restantes

- Não alterar limite dos agentes, ranking de último automático, disponibilidade/ausência, calendário, estabilidade ou modo da barreira de abertura.
- Não criar novas assinaturas HubSpot nem alterar HMAC, workflows, `.env` ou credenciais.
- Não recuperar em massa atribuições históricas, gerar duração retroativa ou normalizar ciclo sem evidência.
- Não incluir refactor de UI, n8n ou métricas não relacionadas à ocupação.
- Não afirmar uma causa única de produção sem ticket/eventos. A resposta à solicitação sobre interface/ticket será incorporada como evidência de reprodução antes de finalizar V-01.
- A necessidade de paginação/refresh e o tamanho real da carteira podem tornar o desenho operacionalmente caro. Gate de desempenho e shadow são obrigatórios; não reduzir segurança silenciosamente para obter vazão.
- O contrato temporal do provider não fornece transação distribuída. Mesmo com este desenho, atraso externo pode gerar janela de desconhecimento; medir idade das observações e deixar explícito esse limite.

## 10. Decisão requerida

**Aprovar ou revisar a proposta de Ciclo F com ocupação por ticket, reservas explícitas, migration aditiva e validação local descritas acima.** Só após autorização de Implementation executar OPS-00 e V-01. Aprovar a implementação local não autoriza publicação, deploy, bootstrap remoto ou enforcement; esses resultados deverão ser preparados para revisão antes de qualquer ação externa.

STATUS desta request é a fonte de progresso; nenhuma tarefa de implementação foi marcada como concluída nesta Planning.
