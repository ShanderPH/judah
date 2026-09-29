# Master plan — contrato HubSpot 2026.09 e fidelidade de lifecycle do JUDAH

**Versão:** final consolidada para aprovação de Implementation
**Classificação:** Ciclo F — refactor arquitetural
**Branch proposta:** `refactor/hubspot-provider-contract-2026-09`
**Request proposta:** `ai-system/requests/refactor/hubspot-provider-contract-2026-09/`
**Plan Artifact:** `01-plan/master-plan.md`
**Estado:** Planning. Não autoriza implementação, mutation remota, migration em produção, alteração de scopes/app HubSpot, deploy, backfill ou `--apply`.

**Base observada durante Planning:** `main` contendo o merge do PR #129 (`62fb21518cd0c0726c80a1050927b268a708912d`). A Implementation deve resolver novamente o HEAD real de `main` antes de criar a branch; este SHA não é uma base imutável.

---

## 1. North Star — arquitetura-alvo

Este documento passa a ser o **norte arquitetural do bounded context HubSpot + Support Lifecycle do JUDAH**.

A regra estrutural é:

```text
HubSpot e demais providers
          ↓
  adapters de integração
          ↓
 evidências/ocorrências
      canônicas
          ↓
    domínio JUDAH
          ↓
projeções + efeitos controlados
```

O HubSpot fornece fatos externos, snapshots e efeitos remotos. O JUDAH é dono da interpretação operacional desses fatos, da identidade de atendimento, da idempotência, da capacidade, da proveniência e das métricas derivadas.

### 1.1 Contrato de camadas

**`apps/integrations/hubspot`** pode:

- autenticar;
- chamar APIs;
- paginar;
- aplicar timeouts;
- classificar erro HTTP/provider;
- converter payload externo em DTOs tipados;
- normalizar formatos técnicos.

**`apps/integrations/hubspot` não pode:**

- decidir qual ciclo fechar;
- criar identidade de atendimento;
- liberar capacidade;
- decidir se uma atribuição foi manual ou automática;
- atualizar métricas de domínio;
- interpretar uma ausência de timestamp como fechamento válido;
- executar regras de negócio do Support.

Essas decisões pertencem ao domínio `apps/support`.

### 1.2 Regra de single-writer

Ao final da refatoração deve existir **um único caminho canônico de escrita para cada fato de domínio**:

| Fato | Writer canônico |
|---|---|
| admitir/abrir ciclo | `conversation_cycle_service.open_or_get_cycle()` |
| fechar ciclo | `ticket_close_service.reconcile_close_occurrence()` |
| confirmar occupancy atual | `owner_reconciliation_service.reconcile_ticket()` ou sucessor explicitamente consolidado |
| reservar/finalizar atribuição | `durable_assignment_service` + `AgentCapacityReservation` |
| materializar ocorrência | `lifecycle_occurrence_service` |
| classificar provenance | `assignment_provenance_service` ou value object compartilhado |
| métricas | agregadores que leem estado persistido canônico |

Handlers, Celery tasks e adapters não podem manter writers paralelos para os mesmos fatos.

### 1.3 Critério arquitetural de revisão

Uma solução não é aceita apenas porque corrige o bug e passa nos testes. Se ela:

- aumentar acoplamento direto HubSpot ↔ domínio;
- introduzir segundo writer para o mesmo fato;
- depender de ordem de webhook;
- inventar identidade/timestamp;
- transformar erro remoto em conjunto vazio;
- duplicar estado que já possui autoridade canônica;

ela viola este North Star e deve voltar para revisão.

---

## 2. Resultado pretendido

Reestruturar a integração HubSpot do JUDAH para que:

1. eventos fora de ordem, duplicados ou parcialmente materializados não produzam divergência de ciclo, ocupação, fechamento, atribuição ou métricas;
2. a identidade de cada atendimento seja derivada de ocorrência externa comprovável, nunca de receipt time, `timezone.now()` ou heurística;
3. reabertura seja representada por um novo ciclo comprovado, preservando os ciclos anteriores;
4. fechamento observado sem horário materializado seja tratado como consistência eventual do provider e reconciliado de forma bounded;
5. sincronização de agentes/equipes use contratos atuais, paginação completa, least privilege e detecção explícita de falta de capability;
6. atribuições automáticas, manuais, administrativas e externas tenham proveniência persistida e mensurável;
7. adapters HubSpot sejam versionados por capability e deixem de depender implicitamente de contratos legados;
8. webhook, CRM readback, Journal e, quando aplicável, Conversations/Help Desk convirjam para o mesmo domínio;
9. erros de autenticação, escopo, paginação incompleta e provider lag nunca sejam interpretados como “zero resultados” ou sucesso;
10. recovery histórico permaneça separado do live traffic, dry-run por padrão e com autorização explícita para escrita.

O objetivo não é eliminar eventual consistency do HubSpot. O objetivo é fazer com que eventual consistency deixe de produzir estado incorreto no JUDAH.

---

## 3. Supersessão do plano anterior

Este master plan **supersede o P0 anterior como direção arquitetural** para novas implementações do domínio HubSpot/Support. O plano anterior continua válido como registro histórico, evidência de decisões e fonte das invariantes que já foram implementadas.

Não existe autorização para remover ou reescrever componentes apenas porque o plano anterior foi supersedido. Cada componente é classificado abaixo.

### 3.1 Matriz KEEP / EVOLVE / REPLACE / REMOVE

| Componente/contrato atual | Decisão | Motivo |
|---|---|---|
| `WebhookEvent` | **KEEP** | ledger bruto, auditoria e dedup de transporte continuam necessários |
| HMAC v1/v3 | **KEEP** | fronteira de segurança antes da persistência/efeitos |
| `SupportConversationCycle` | **KEEP / EVOLVE** | identidade temporal do atendimento permanece; passará a consumir occurrence canônica |
| `SupportTicketOccupancy` | **KEEP / EVOLVE** | continua sendo estado operacional atual, não histórico |
| `AgentCapacityReservation` | **KEEP** | reserva durável preserva efeitos ambíguos e capacidade |
| `AssignmentAttempt` | **KEEP / EVOLVE** | saga existente é válida; provenance e integração serão normalizadas |
| `ticket_close_service` | **EVOLVE** | torna-se writer único de fechamento baseado em occurrence comprovada |
| `owner_reconciliation_service` | **EVOLVE** | reconcilia estado; deixa de tentar criar/descobrir identidade histórica tardiamente |
| `capacity_service` | **KEEP / EVOLVE** | preserva capacidade identificada e lock ordering |
| `durable_assignment_service` | **KEEP / EVOLVE** | permanece dono do efeito de assignment/reserva |
| `get_team_members()` atual | **REPLACE** | usa Owners API sem paginação completa e mistura membership com owner listing |
| chamadas HubSpot raw/dispersas | **REPLACE** | devem convergir para adapters/version registry |
| erro `missing_close_time` como falha estrutural | **REMOVE** | passa a `provider_materialization_pending` + reconciliation |
| inferência tardia de ciclo por snapshot owner/capacity | **REMOVE** | identidade deve nascer da ocorrência de entrada |
| inferência “não fui eu = manual” | **REMOVE** | usar provenance determinística ou `unknown_external` |
| historical repair no live path | **PROHIBITED** | recovery histórico continua lane isolada |
| métricas por interpretação posterior de logs | **REPLACE** | derivar de estado/ciclo/provenance persistidos |

### 3.2 Mapeamento do P0 anterior

| Bloco anterior | Destino neste plano |
|---|---|
| capacidade identificada por ticket | **absorvido e preservado** |
| reservas duráveis | **absorvido e preservado** |
| provider readback / fail-closed | **absorvido e ampliado** |
| fechamento fora de ordem | **absorvido no occurrence-first** |
| reparador histórico bounded | **preservado como REC lane** |
| owner/manual reconciliation | **absorvido e movido para provenance + occurrence** |
| sync de equipe/owners | **substituído pelo HubSpot Platform Contract + TeamRosterProvider** |
| tratamento de eventual consistency | **substituído por pending/reconciliation explícito** |
| observabilidade funcional | **ampliada para capabilities/roster/lifecycle** |

A Implementation deve usar esta matriz para evitar reescrever o que já está correto ou manter duas soluções para a mesma responsabilidade.

---

## 4. Escopo obrigatório do P0 vs. spikes opcionais

### 4.1 P0 obrigatório — não negociável

O P0 só pode ser considerado correto com:

- HubSpot Platform Contract/version registry;
- capability matrix e preflight;
- TeamRosterProvider completo e paginado;
- `SupportLifecycleOccurrence`;
- occurrence-first para open/close/owner;
- `provider_materialization_pending` para fechamento sem timestamp;
- bounded reconciliation;
- eliminação da inferência tardia de ciclo no live path;
- provenance unificada;
- webhook configuration governance;
- observabilidade/readiness correspondente;
- testes PostgreSQL/Redis/Celery e sandbox para capacidades obrigatórias.

### 4.2 Spikes opcionais — não podem bloquear correção básica

Os itens abaixo podem melhorar robustez/fidelidade, mas **não são pré-condição para a arquitetura ser correta**:

- Webhooks Journal como fonte adicional de recovery;
- Conversations/Help Desk como fonte de provenance/correlação;
- uso de eventos extras como `hs_pipeline_stage`, se suportados e comprovados;
- automações/MCP para operação assistida.

Se um spike falhar, for indisponível para a conta ou exigir scopes desproporcionais, o P0 deve continuar correto com webhook + CRM readback + bounded reconciliation + quarantine.

---

## 5. Controles que devem ser preservados

- `WebhookEvent` como ledger bruto/idempotente.
- HMAC v1/v3 antes de efeitos.
- `SupportConversationCycle` e sua natural key temporal.
- `SupportTicketOccupancy` e `AgentCapacityReservation`.
- `AssignmentAttempt` e saga de efeito remoto.
- provider readback antes de efeitos críticos.
- fail-closed para owner/estágio.
- fencing, leases, writer authority e lock ordering.
- stale-event guard.
- `reconcile_ticket_closures` dry-run por padrão.
- separação entre live traffic e recovery histórico.

Este plano é incremental sobre os hotfixes #116, #119, #124 e #126–#129; não reimplementa esses fluxos do zero.

---

## 6. Evidências atuais

| Evidência | Consequência |
|---|---|
| `get_team_members()` usa Owners API `get_page(limit=100)` sem paginação e filtra team em memória | roster pode ser incompleto; membership precisa de adapter próprio |
| manifesto versionado não declara `crm.objects.owners.read`, mas runtime chama Owners API | capability/scopes precisam ser verificados antes do job |
| falha de team sync termina retornando `0` | erro remoto não pode ser semanticamente igual a “nenhum membro novo” |
| `capacity_projection_cycle_identity_unresolved` ainda ocorre | owner/capacity tentam resolver identidade tarde demais |
| provider pode indicar stage fechado antes de `entered_closed_at` existir | precisa de estado pending/reconciliation, não erro estrutural |
| fechamento já possui resolver temporal e classificação | esse contrato deve ser o único caminho de materialização |
| `SupportConversationCycle` já modela reopen como novo ciclo | nova camada deve alimentar esse contrato, não contorná-lo |
| existem múltiplos campos de origem de assignment | proveniência deve ser unificada, não inferida de forma diferente por handler |
| webhook manifest atual assina entrada NOVO, entrada FECHADO e owner | desired config e published config precisam de readback/drift detection |

---

## 7. Princípios obrigatórios

1. Ocorrência antes da projeção.
2. Receipt time nunca cria identidade.
3. Payload de webhook é evidência temporal, não estado atual.
4. Snapshot atual não substitui histórico.
5. Provider lag é estado operacional, não corrupção.
6. Erro remoto não é conjunto vazio.
7. Nenhuma fonte isolada precisa ser suficiente para todos os fatos.
8. Uma ocorrência idempotente produz no máximo um efeito/projeção por ciclo.
9. Recovery histórico e live traffic nunca compartilham drain irrestrito.
10. Least privilege: não conceder automaticamente todos os scopes citados por uma mensagem 403.
11. Nenhum I/O externo dentro de DB locks.
12. Ausência de evidência não libera capacidade nem fecha ciclo.
13. Adapters traduzem contratos externos; regras de negócio ficam no domínio.
14. Handler/task orquestra; service de domínio decide.
15. Um fato de domínio tem um único writer canônico.

---

## 8. Arquitetura alvo detalhada

```text
HubSpot webhooks ─┐
CRM readback ─────┼──> HubSpot adapters/version registry
Journal ──────────┤             │
Conversations ────┘             ▼
                         ProviderObservation
                                │
                                ▼
                    SupportLifecycleOccurrence
                     append-only / idempotente
                                │
             ┌──────────────────┼──────────────────┐
             ▼                  ▼                  ▼
     SupportConversationCycle  Occupancy       Assignment provenance
             │                  │                  │
             ▼                  ▼                  ▼
      Close/reopen projection  Capacity       Metrics / analytics
```

`WebhookEvent` continua sendo o raw ledger. Criar uma camada de domínio `SupportLifecycleOccurrence`, sem duplicar payload bruto.

Campos propostos: `source_system`, `source_account_id`, `hubspot_ticket_id`, `occurrence_type`, `occurred_at`, `evidence_status`, `evidence_source`, `evidence_key`, `source_event_id`, `provider_updated_at`, `observation_id`, `processing_status`, `retry_count`, `next_reconcile_at`, `last_error_code`, timestamps.

`occurrence_type` inicial:

- `entered_support_queue`;
- `closed`;
- `owner_changed`.

Reopen é consequência de nova ocorrência de entrada após fechamento, salvo evidência externa distinta e comprovada.

`evidence_status`:

- `proven`;
- `provider_materialization_pending`;
- `ambiguous`;
- `rejected`.

Ocorrência `proven` exige timestamp comprovado. Pending não abre nem fecha ciclo.

---

## 9. HubSpot Platform Contract

### 9.1 Version registry

Criar registry explícito por capability. Não assumir que toda família tem a mesma versão.

```text
Tickets read/write -> latest stable date-based version suportada
Teams             -> 2026-09
Conversations     -> 2026-09
Webhooks Journal  -> latest stable suportada para essa API
```

Encapsular path, paginação, timeout, retry classification e parsing. Proibir novas chamadas raw `requests` fora do adapter versionado, salvo exceção documentada/testada.

### 9.2 Capability matrix e preflight

Criar `check_hubspot_capabilities`, somente leitura, com saída estruturada por capability. 401/403 obrigatórios degradam readiness funcional e bloqueiam o job dependente. Nunca retornar `0`/`[]` como sucesso quando o provider falhou.

Matriz mínima:

- tickets read;
- tickets write;
- owners read, se mantido;
- teams membership;
- users read;
- conversations read — opcional;
- journal/snapshot — opcional.

### 9.3 TeamRosterProvider

Substituir “listar owners e filtrar team” por:

```text
TeamRosterProvider
├── Teams API: membership
├── Users API: identidade/status
└── Owner resolver: CRM owner id quando necessário
```

Requisitos:

- paginação completa;
- `complete: bool`;
- cursor auditável;
- budget;
- dedup;
- membro removido/inativo explícito;
- sync incompleto nunca marcado como completo;
- erro = `provider_unavailable`;
- métrica de idade do último sync completo.

Teams 2026.09 deve ser avaliada como fonte primária de membership. Owners fica restrito a mapping de CRM owner se realmente necessário.

---

## 10. Canonical Lifecycle Occurrence Resolver

Criar `apps/support/lifecycle_occurrence_service.py`.

Responsabilidades:

- normalizar observação;
- validar identidade;
- classificar evidência temporal;
- deduplicar;
- persistir ocorrência/pending;
- despachar projeções após commit;
- nunca executar effect externo.

### 10.1 Entrada em NOVO

Ocorrência comprovada → `open_or_get_cycle()` com timestamp real. Duplicata = no-op; stale não altera ciclo novo; nova entrada enquanto ciclo ativo = conflito/repair, nunca fechamento implícito.

### 10.2 Fechamento

Evento com timestamp de FECHADO → ocorrência `closed/proven` → `reconcile_close_occurrence()`.

Snapshot com `stage=closed` e `entered_closed_at=None`:

- não chamar `_apply_ticket_closed`;
- não fechar occupancy;
- não liberar capacidade;
- persistir `provider_materialization_pending`;
- reagendar readback bounded;
- quando timestamp aparecer, promover para `proven` e materializar uma vez.

### 10.3 Reconciliação bounded

Task: `support.task_reconcile_lifecycle_occurrence`.

- exponential backoff;
- max attempts e max age configurados;
- 429/5xx/network retryable;
- 401/403 = capability failure, não retry cego;
- 404 único inconclusivo;
- fim do budget → `ambiguous/repair_required` visível em readiness.

Nenhum loop infinito.

---

## 11. Reopen e identidade de ciclo

Nova regra:

```text
stage-entry occurrence -> cycle
owner occurrence       -> projeta sobre cycle existente quando resolvível
capacity snapshot       -> nunca cria identidade histórica
close occurrence       -> fecha cycle temporalmente compatível
```

`capacity_projection_cycle_identity_unresolved` deixa de ser resultado normal do live path.

Se owner/capacity chegar antes da ocorrência de abertura:

- occupancy pode refletir owner atual de forma conservadora;
- lifecycle fica pending/repair;
- métricas de queue/handle time não são inventadas;
- quando a abertura for comprovada, projetar idempotentemente.

Critério obrigatório: `open1 -> ownerA -> close1 -> open2 -> ownerB -> close2`, entregue em ordens diferentes e com duplicatas, deve produzir exatamente dois ciclos, dois fechamentos, nenhum revival do ciclo 1, occupancy terminal e attribution por ciclo correta.

---

## 12. Proveniência de atribuição e métricas

Taxonomia única:

- `automatic_assignment`;
- `manual_assignment`;
- `owner_change`;
- `forced_reassignment`;
- `external_integration`;
- `unknown_external`.

Mapear consistentemente para `AssignmentAttempt`, `AssignmentLog`, `ConversationReassignment`, `ConversationInstanceAttendant` e analytics.

Não inferir “manual” apenas porque o JUDAH não iniciou o PATCH.

Regra:

1. `AssignmentAttempt` correlacionável + owner confirmado → origem do attempt;
2. `ConversationReassignment` administrativa → forced/admin;
3. ator/origem HubSpot comprovável → classificar;
4. sem evidência → `unknown_external`.

Criar service/value object de provenance para impedir derivação divergente entre handlers.

Métricas agregam por ciclo/provenance persistidos, não por interpretação posterior de logs.

---

## 13. Webhook configuration governance

Projeto versionado deve representar desired state e produção precisa de verification/readback.

Comparar:

- app/project identity;
- subscriptions esperadas/publicadas;
- target URL;
- status ativo;
- capabilities/scopes.

Assinaturas novas como `hs_pipeline_stage` só entram se oficialmente suportadas, testadas em sandbox, convergirem pelo mesmo occurrence resolver e forem idempotentes cross-trigger.

---

## 14. Spikes opcionais

### 14.1 INT-05 — Webhooks Journal

Implementar inicialmente atrás de `LifecycleEvidenceProvider`.

Ordem de evidência proposta:

1. webhook direto;
2. CRM readback;
3. Journal/snapshot para recovery quando capability estiver validada.

O spike deve decidir: `enable`, `fallback only` ou `not adopted`.

Nenhuma das três decisões pode invalidar o P0 básico.

### 14.2 INT-06 — Conversations / Help Desk

Usar 2026.09 como spike de correlação, não substituição automática de Tickets CRM.

Validar em sandbox:

- thread↔ticket;
- assignment↔owner;
- transferências;
- Help Desk vs Inbox;
- múltiplas threads;
- reopen;
- ator/origem.

Se for evidência estável, usar para enriquecer provenance. Se não for 1:1, manter domínios separados. Conversations não cria `SupportConversationCycle` sozinho.

---

## 15. Persistência e migrations

### DB-01 — `SupportLifecycleOccurrence`

Migration aditiva. Constraints:

- unique evidence key;
- `occurred_at` obrigatório quando `proven`;
- pending não pode ser `processed`;
- retry >= 0;
- índices por ticket/type/time e status/next_reconcile.

Nenhum histórico existente é alterado pela migration.

### DB-02 — provenance

Primeiro reutilizar campos existentes. Nova tabela só se a correlação realmente exigir persistência independente.

---

## 16. Gate arquitetural antes do coding estrutural

### ARCH-01 — inventário de writers/readers e mapa de autoridade

Depois de `V-01` e antes de `DB-01/BE-01`, produzir:

`00-context/domain-write-map.md`

O documento deve inventariar todos os caminhos que hoje:

- criam/alteram `SupportConversationCycle`;
- criam/alteram `NewConversation`;
- criam/alteram `AssignedConversation`;
- criam `ClosedConversation`;
- alteram `SupportTicketOccupancy`;
- alteram `Agent.current_simultaneous_chats`;
- criam/finalizam `AssignmentAttempt` e reservas;
- registram `AssignmentLog`/`ConversationReassignment`;
- agregam queue/agent metrics;
- chamam HubSpot para owner/stage/team/users;
- executam recovery histórico.

Para cada path, registrar:

```text
entrada -> adapter/read -> ocorrência -> service de domínio -> projeções -> external effect
```

Classificar cada writer como:

- canonical;
- migrate-to-canonical;
- read-only;
- remove;
- historical-only.

**Gate:** `DB-01` e `BE-01` não começam enquanto houver writer relevante sem owner arquitetural definido.

### ARCH-02 — purity check de adapters

Durante review/VERIFY, auditar que nenhum novo adapter HubSpot executa regra de domínio. Pode ser teste estrutural simples/import boundary + revisão estática.

### ARCH-03 — single-writer audit

Antes de `OPS-01`, provar que cada fato listado na seção 1.2 possui um único writer canônico e que handlers/tasks delegam para ele.

---

## 17. Plano de execução

| ID | Trabalho | Dependência | Evidência de saída |
|---|---|---|---|
| OPS-00 | criar branch e registrar HEAD/status | aprovação | branch isolada |
| V-01 | RED tests: scopes/roster, missing close time, cycle unresolved | OPS-00 | regressões reproduzidas |
| ARCH-01 | inventário de writers/readers e mapa de autoridade | V-01 | `domain-write-map.md`; nenhum writer sem destino |
| INT-01 | version registry + adapters tipados | ARCH-01 | chamadas críticas encapsuladas |
| INT-02 | capability matrix + preflight/readiness | INT-01 | 401/403 != vazio |
| INT-03 | TeamRosterProvider + paginação | INT-01/02 | roster completo/partial explícitos |
| DB-01 | `SupportLifecycleOccurrence` + migration | ARCH-01/V-01 | migration/constraints verdes |
| BE-01 | `lifecycle_occurrence_service` | DB-01 | open/close/owner idempotentes |
| BE-02 | pending close + reconciliation bounded | BE-01/INT-01 | missing_close_time deixa de quebrar projeção |
| BE-03 | occurrence-first em cycle/occupancy/owner | BE-01/02 | live não inventa ciclo via snapshot |
| BE-04 | provenance unificada | BE-03 | auto/manual/external mensuráveis |
| INT-04 | governance/readback de webhooks | INT-02 | drift detectável |
| INT-05 | spike Journal — opcional | INT-01/02 | decisão enable/fallback/not adopted |
| INT-06 | spike Conversations — opcional | INT-01/02 | decisão de correlação/provenance |
| OBS-01 | SLIs/readiness/alerts | BE-02/03, INT-03 | lag/pending/scope/roster visíveis |
| DB-02 | analytics/provenance mínimos | BE-04 | migration mínima ou reuso documentado |
| ARCH-02 | purity check de adapters | INT/BE principais | adapter sem regra de domínio |
| V-02 | PostgreSQL/Redis/Celery integration/concurrency | BE/DB | invariantes concorrentes |
| V-03 | HubSpot sandbox E2E | INT obrigatórios | contratos obrigatórios comprovados |
| V-04 | full suite + ruff + mypy + writer audit | V-02/03 | quality gates completos |
| ARCH-03 | single-writer audit final | V-04 | um writer por fato de domínio |
| OPS-01 | runbook release/shadow/enforce/rollback | ARCH-03 | plano revisável |
| OPS-02 | deploy aditivo em off/shadow | autorização separada | zero repair histórico |
| OPS-03 | promoção live | shadow + autorização | gates live verdes |
| REC-01 | dry-run histórico pós-cutover | OPS-03 | relatório sem writes |
| REC-02 | repair bounded | autorização por lote | só coorte aprovada |
| CLN-01 | remover paths legados | estabilidade | nenhum caller restante |

**Observação:** falha ou descarte de `INT-05/INT-06` não impede `V-04/OPS-01` se o P0 obrigatório estiver verde e a decisão do spike estiver documentada.

---

## 18. Watch list

### Integração

- `apps/integrations/hubspot/client.py`;
- novos adapters em `apps/integrations/hubspot/`;
- `hubspot-app/src/app/app-hsmeta.json`;
- `hubspot-app/src/app/webhooks/judah-webhooks-hsmeta.json`.

### Support domain

- `apps/support/models.py`;
- `apps/support/conversation_cycle_service.py`;
- `apps/support/ticket_close_service.py`;
- `apps/support/owner_reconciliation_service.py`;
- `apps/support/capacity_service.py`;
- `apps/support/durable_assignment_service.py`;
- `apps/support/auto_assign_service.py`;
- `apps/support/tasks.py`;
- `apps/support/assignment_readiness.py`;
- `apps/support/error_catalog.py`;
- novo `apps/support/lifecycle_occurrence_service.py`;
- novo provenance service/value object, se necessário.

### Webhooks

- `apps/webhooks/services.py`;
- handler HubSpot e normalizers necessários.

HMAC não muda.

### Analytics

- agregadores que hoje dependam de projeções ambíguas.

Mudança fora desta watch list exige registrar justificativa em `STATUS.md` e, se alterar contrato arquitetural, revisar o master plan.

---

## 19. Critérios de aceitação

| ID | Critério | Bloqueia rollout se |
|---|---|---|
| AC-01 | capability contract 200/401/403/429/5xx | erro virar vazio/sucesso |
| AC-02 | roster 0/1/100/>100 + paginação | partial marcar complete |
| AC-03 | close sem timestamp e convergência posterior | timestamp inventado/liberação precoce |
| AC-04 | reopen com ordem invertida/duplicatas | ciclo antigo ressuscitar |
| AC-05 | cross-trigger mesmo fato | dois ciclos/effects |
| AC-06 | owner antes do cycle | métrica inventada/capacidade insegura |
| AC-07 | provenance auto/manual/external | unknown virar manual sem prova |
| AC-08 | close/reopen/transfer concorrentes | drift/double count |
| AC-09 | snapshot antigo vs revisão nova | dado antigo vencer |
| AC-10 | retry/restart | loop infinito/duplicate effect |
| AC-11 | live + historical | repair tocar fora da coorte |
| AC-12 | manifest drift | deploy “ready” com config obrigatória divergente |
| AC-13 | regressão dos controles atuais | perda de fail-closed/idempotência/fencing |
| AC-14 | métricas por ciclo | agregação por ticket quando ciclo é unidade correta |
| AC-15 | segurança | token/PII/payload novo em log |
| AC-16 | adapter purity | regra de domínio dentro de integration adapter |
| AC-17 | single writer | dois caminhos mutando o mesmo fato canônico |
| AC-18 | supersession | implementação reintroduzir path marcado REMOVE/REPLACE sem ADR/revisão |

---

## 20. Testes críticos

- **T-01:** capability preflight com respostas classificadas.
- **T-02:** team pagination com cursor interrompido e partial result.
- **T-03:** missing close time — primeiro read sem timestamp, segundo com timestamp; exatamente um fechamento.
- **T-04:** pending que nunca converge → repair/ambiguous sem timestamp fabricado.
- **T-05:** permutações de reopen/close/owner com duplicatas.
- **T-06:** cross-trigger duplicate → um ciclo.
- **T-07:** provenance de effect JUDAH vs owner externo.
- **T-08:** snapshot antigo concorrendo com revisão nova em PostgreSQL real.
- **T-09:** atomicidade de lifecycle + occupancy + capacity.
- **T-10:** worker restart preservando retry bounded.
- **T-11:** HubSpot sandbox para membership, ticket, owner, stage, reopen e config readback.
- **T-12:** historical dry-run determinístico e sem writes.
- **T-13:** architecture test garantindo que handlers/tasks deleguem para writers canônicos.
- **T-14:** import/purity test garantindo que adapters HubSpot não importem services de domínio de Support para decidir lifecycle/capacity.
- **T-15:** regressão dos hotfixes #116/#119/#124/#126–#129.

---

## 21. Observabilidade

SLIs mínimos:

- capability check por outcome;
- team roster sync outcome e age do último completo;
- lifecycle occurrence por type/status;
- pending age;
- reconcile outcome;
- cycle identity unresolved;
- close materialization pending;
- assignment provenance;
- webhook config drift;
- provider latency/429/5xx.

Readiness separa:

- API liveness;
- provider connectivity;
- HubSpot capabilities;
- roster freshness;
- assignment health;
- lifecycle projection health.

Falha em capability opcional de Journal/Conversations não derruba assignment readiness. Falha em capability obrigatória para owner effects degrada assignment.

---

## 22. Rollout

### Fase 0 — Local

- branch;
- RED tests;
- ARCH-01;
- migration local;
- Redis/Celery real;
- lint/mypy/full suite.

### Fase 1 — Deploy aditivo

- mesmo SHA em API/worker/beat;
- occurrence mode off;
- preflight read-only;
- nenhuma mudança de scope implícita.

### Fase 2 — Provider contract

- autorizar scopes/app;
- roster novo em shadow;
- comparar old/new;
- resultado parcial nunca promove readiness.

### Fase 3 — Lifecycle shadow

- occurrence resolver observa e compara sem substituir projeção efetiva;
- medir pending close, cycle identity, lag e provenance.

### Fase 4 — Enforce live

Somente com:

- capabilities obrigatórias verdes;
- roster fresco/completo;
- zero nova identity divergence normal;
- pending close dentro do SLO definido;
- sem double projection;
- ARCH-03 aprovado;
- API/worker/beat no mesmo SHA.

### Fase 5 — Historical dry-run

Somente após live estabilizado.

### Fase 6 — Historical apply

Autorização explícita e lote bounded.

### Fase 7 — Cleanup

Remover paths legados após janela representativa e confirmação de ausência de callers.

---

## 23. Stop conditions

Parar promoção se houver:

- 401/403 obrigatório;
- roster partial tratado como complete;
- aumento de cycle identity unresolved em coorte nova;
- pending close envelhecido além do limite;
- fechamento duplicado;
- occupancy/cycle divergentes;
- owner manual sobrescrito;
- duplicate PATCH;
- drift de capacidade;
- retry infinito;
- 429 sustentado;
- webhook config drift obrigatório;
- SHAs diferentes;
- repair histórico fora da coorte;
- regra de domínio nova dentro de adapter HubSpot;
- segundo writer para fato já canônico;
- path marcado `REMOVE` voltando ao live traffic sem revisão do plano.

---

## 24. Rollback

Rollback por camada:

1. suspender owner effects se houver risco de write externo;
2. voltar occurrence enforcement para shadow/off;
3. manter ledger/occurrences para auditoria;
4. manter migration aditiva;
5. classificar reservas/`external_applied` antes de retornar writer;
6. não liberar ambíguos por conveniência;
7. reverter adapter/version apenas se contrato anterior ainda estiver suportado e capability matrix estiver verde;
8. reverse migration de dados não é rollback padrão de produção.

O runbook deve registrar cutover timestamp, coorte afetada e writers ativos em cada lado da transição.

---

## 25. P0 concluído somente quando

- [ ] North Star e supersession matrix permanecem verdadeiros após Implementation.
- [ ] ARCH-01 inventariou todos os writers/readers relevantes.
- [ ] Teams/Users/Owners contract validado com paginação completa.
- [ ] `MISSING_SCOPES` eliminado nas capabilities obrigatórias.
- [ ] scopes efetivos documentados com least privilege.
- [ ] API versions registradas explicitamente.
- [ ] stage fechado sem close time entra em pending e converge sem timestamp inventado.
- [ ] novo live traffic não usa `capacity_projection_cycle_identity_unresolved` como estado normal.
- [ ] close→reopen→owner→close passa com ordens/duplicatas.
- [ ] auto/manual/external possuem provenance determinística ou `unknown_external`.
- [ ] métricas por ciclo batem em amostra controlada.
- [ ] desired/published webhook config sem drift obrigatório.
- [ ] adapters HubSpot não contêm decisão de lifecycle/capacity/provenance.
- [ ] cada fato de domínio possui um writer canônico.
- [ ] PostgreSQL concurrency, Redis/Celery e HubSpot sandbox verdes.
- [ ] Ruff, mypy, Django checks, migrations e full suite verdes.
- [ ] shadow observado em janela operacional representativa.
- [ ] zero novo divergent cycle pós-cutover.
- [ ] historical dry-run executado antes de qualquer apply.
- [ ] rollback exercitado em ambiente seguro.

**Journal e Conversations não são obrigatórios para fechar o P0 se os respectivos spikes concluírem `not adopted` com justificativa e o contrato obrigatório acima estiver verde.**

---

## 26. Estrutura da request

```text
ai-system/requests/refactor/hubspot-provider-contract-2026-09/
  00-context/
    production-findings.md
    hubspot-capability-matrix.md
    current-call-inventory.md
    domain-write-map.md
    supersession-matrix.md
  01-plan/
    master-plan.md
  02-artifacts/
    backend/
    database/
    devops/
  03-verification/
    local-results.md
    postgres-concurrency.md
    hubspot-sandbox.md
    shadow-comparison.md
    architecture-audit.md
  04-iteration/
  05-deployment/
    release-and-rollback.md
    live-gates.md
    historical-recovery.md
  STATUS.md
  HANDOFF.md
```

---

## 27. STATUS inicial proposto

```yaml
request: refactor/hubspot-provider-contract-2026-09
cycle: F
state: PLAN
opened_at: 2026-09-28T10:52:00-03:00
last_update: 2026-09-28T10:52:00-03:00
agent_run_id: ""
current_blockers:
  - "Implementation ainda não autorizada."
  - "Scopes/capabilities HubSpot precisam de verificação no app/sandbox antes de mutation."
next_action: "Felipe: revisar e aprovar 01-plan/master-plan.md final para iniciar OPS-00/V-01/ARCH-01."
artifacts_generated:
  - 01-plan/master-plan.md
verification_runs: 0
```

---

## 28. Decisão requerida

Aprovar este Ciclo F para iniciar somente **Implementation local** por `OPS-00`, `V-01` e `ARCH-01`.

A aprovação do master plan não autoriza:

- mudança de scopes/publicação HubSpot;
- deploy;
- migration remota;
- feature flag em produção;
- `--apply`;
- replay/backfill;
- owner mutation em produção.

Cada ação permanece um gate separado.
