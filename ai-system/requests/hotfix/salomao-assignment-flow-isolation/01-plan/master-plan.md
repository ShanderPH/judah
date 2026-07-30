# Master Plan — Hotfix de isolamento e convergência Salomão ↔ atribuição automática

## 1. Identificação

- **Request:** `hotfix/salomao-assignment-flow-isolation`
- **Ciclo:** M — incidente de produção
- **Destino:** PR urgente para `main`
- **Prioridade:** P0
- **Estado deste artefato:** PLAN — aguardando aprovação para implementação
- **Escopo aprovado:** correção estrutural do roteamento, flag independente do Salomão, convergência para atendimento humano/Matchmaker, observabilidade, recuperação controlada e remediação RLS das tabelas expostas no Supabase
- **Fora do escopo desta aprovação:** alterar subscriptions/flags em produção, replay, backfill, mudar owner/stage de tickets, aplicar migration remota, deploy, merge ou recuperação operacional

## 2. Objetivo

Restabelecer a confiabilidade da atribuição automática sem desmontar a integração entre o Supervisor Salomão e o núcleo operacional do JUDAH.

O fluxo final deve permitir:

1. Salomão ligado e elegível: processar a conversa pela IA, respeitando autoridade humana, idempotência e lifecycle.
2. Salomão desligado ou inelegível: convergir determinística e idempotentemente para o pipeline humano e, quando o ticket satisfizer os contratos de suporte, para o Matchmaker.
3. Atribuição automática ligada: continuar ingerindo e atribuindo tickets independentemente do estado operacional do Salomão.
4. Eventos HubSpot fora de ordem: não retroceder snapshots/lifecycle e, ao mesmo tempo, não perder ocorrências operacionais válidas de entrada em NOVO.
5. Tabelas operacionais do Supabase: deixar de ser acessíveis a `anon`/`authenticated` sem bloquear API, worker, beat, migrations ou rotinas de recuperação autorizadas.

## 3. Restrições e premissas confirmadas

### 3.1 Subscriptions atualmente desativadas

Foram desativadas individualmente:

- `hs_last_message_from_visitor`;
- `hs_pipeline_stage`;
- `hs_v2_date_entered_939271304`.

O projeto/app de webhooks não foi desativado. Permanecem chegando eventos do app HubSpot `35466481` — **Judah HubSpot Integration**.

### 3.2 Autoridade da atribuição

A ocorrência primária para entrada na atribuição automática é:

```text
ticket.propertyChange
propertyName = hs_v2_date_entered_939275049
```

O Matchmaker só pode atribuir quando, após hidratação/revalidação:

- pipeline de suporte = `636459134`;
- estágio NOVO = `939275049`;
- owner atual vazio;
- runtime com autoridade;
- `AUTO_ASSIGNMENT_ENABLED=true`;
- agente elegível e disponibilidade HubSpot fresca;
- ciclo/ocorrência válido e idempotente.

`hs_pipeline_stage` é um sinal compartilhado e redundante. Sua ausência não deve inviabilizar o caminho primário por `hs_v2_date_entered_939275049`.

### 3.3 Falha comprovada

O PR #97 passou a suprimir todos os efeitos de um evento classificado como `stale_event`. Isso protege snapshots e decisões de IA, mas também impede o dispatch de `AUTO_ASSIGNMENT`.

Em produção, eventos de owner da triagem legado podem ser processados antes do evento calculado de entrada em NOVO, embora o NOVO represente uma ocorrência válida. O webhook é marcado como processado, mas não cria ciclo, fila nem tentativa durável.

O hotfix não deve simplesmente desabilitar a proteção de ordenação. Deve separar:

- **ordenação da projeção:** pode rejeitar evento antigo para não retroceder lifecycle/snapshot;
- **identidade da ocorrência operacional:** uma entrada em NOVO válida deve ser entregue ao protocolo idempotente de ciclos/atribuição mesmo quando sua projeção é mais antiga que outro evento independente.

## 4. Arquitetura alvo

### 4.1 Capacidades independentes

Introduzir capacidades explícitas, sem usar uma única flag para controlar responsabilidades diferentes:

| Capacidade | Controle | Comportamento |
|---|---|---|
| Receber/persistir webhook | endpoint + assinatura HMAC | Sempre ativo para subscriptions configuradas |
| Projetar lifecycle | schema/lifecycle disponível | Registra evento e preserva ordenação |
| Executar Salomão | `SALOMAO_SUPERVISOR_ENABLED` | Autoriza somente execução/resposta da IA |
| Reconciliar mensagens da IA | `SALOMAO_WAITING_RECONCILIATION_ENABLED` | Autoriza polling de threads `WAITING_FOR_CUSTOMER` |
| Ingerir fila humana | `may_ingest_queue()` | Independente do Salomão |
| Atribuir automaticamente | `AUTO_ASSIGNMENT_ENABLED` + `may_assign()` | Independente do Salomão |
| Escrever estado de roteamento | runtime authority | API/worker/beat conforme contrato existente |

Valores seguros de rollout:

```text
SALOMAO_SUPERVISOR_ENABLED=false
SALOMAO_WAITING_RECONCILIATION_ENABLED=false
AUTO_ASSIGNMENT_ENABLED=true
```

Compatibilidade:

- introduzir as novas flags com default derivado do comportamento atual apenas no código;
- em produção, definir valores explícitos nos três serviços;
- não reutilizar `AI_ROUTING_ENABLED` como kill switch de todo o domínio, pois essa flag também controla montagem de rotas e comportamento legado;
- documentar precedência e remover ambiguidades entre `AI_ROUTING_ENABLED`, rollout percentual e `SALOMAO_V1_AS_TEAM_AGENT`.

### 4.2 Matriz de convergência

| Evento/estado | Salomão ligado e elegível | Salomão desligado/inelegível |
|---|---|---|
| Entrada em estágio da IA | Supervisor | handoff determinístico para suporte humano |
| Nova mensagem em thread da IA | verificar direção/autoridade e Supervisor | handoff/reconciliação humana; nunca `safe_noop` final |
| Falha transitória da IA | retry limitado e auditado | handoff ao esgotar orçamento |
| Canal sem resposta automática | handoff | handoff |
| Humano já participando | preservar humano | preservar humano |
| Ticket já em suporte NOVO, sem owner | não sequestrar para IA | ingerir Matchmaker |
| Handoff coloca ticket em suporte NOVO | aguardar evento idempotente ou reconciliar ocorrência | ingerir Matchmaker uma única vez |
| Ticket com owner | não autoatribuir | não autoatribuir |

O fallback deve usar uma única operação de domínio, por exemplo `converge_to_human_support(...)`, responsável por:

1. re-hidratar ticket/rota/owner antes do efeito;
2. preservar autoridade humana existente;
3. mover para o pipeline/estágio humano apenas quando necessário;
4. registrar motivo, origem e idempotency key;
5. produzir/confirmar a ocorrência de suporte NOVO;
6. chamar a ingestão do Matchmaker somente após confirmação do estado elegível;
7. não enviar resposta, alterar stage ou atribuir duas vezes em retries.

Não duplicar essa lógica entre webhook handler, watchdog, execution e handoff tasks.

### 4.3 Ordenação por domínio

Substituir o gate global “evento stale não produz efeitos” por classificação de efeitos:

| Classe | Evento antigo pode executar? | Proteção |
|---|---|---|
| Atualização de snapshot/lifecycle | Não | cursor monotônico do provider |
| Resposta/fechamento/efeito de IA | Não sem revalidação atual | autoridade, message ID e provider re-fetch |
| Owner change | Somente após re-fetch atual | não sobrescrever owner mais novo |
| Entrada calculada em suporte NOVO | Sim, como ocorrência | `entered_stage_at` + `source_event_id` + ciclo idempotente |
| Fechamento calculado | Somente pelo protocolo idempotente de fechamento | ciclo atual + estado provider |

Implementar um contrato tipado, por exemplo `EffectOrderingPolicy`, em vez de condição especial espalhada:

```text
PRESERVE_PROJECTION_ONLY
REVALIDATE_CURRENT_PROVIDER_STATE
PROCESS_IDEMPOTENT_OCCURRENCE
```

Para `AUTO_ASSIGNMENT`, `stale_event` continua impedindo rewind da projeção, mas a ocorrência segue para o serviço de ciclo. Antes de enfileirar, o serviço revalida pipeline, estágio e owner atuais na HubSpot.

## 5. Plano de implementação

### Gate A — Baseline, contratos e testes de reprodução

**Objetivo:** congelar o comportamento observado antes da mudança.

#### BE-01 — Reproduzir a corrida do PR #97

Arquivos previstos:

- `apps/webhooks/tests/test_services.py`;
- `apps/ai_agents/tests/test_lifecycle.py`;
- `apps/webhooks/tests/test_hubspot_handler.py`;
- fixtures compartilhadas existentes, se aplicável.

Casos:

1. owner removido em `T+591 ms` é processado primeiro;
2. `hs_v2_date_entered_939275049` ocorrido em `T` chega depois;
3. lifecycle não retrocede;
4. ocorrência NOVO chega uma única vez ao serviço de ciclos;
5. duplicate delivery não cria segundo ciclo/fila/tentativa;
6. evento genuinamente antigo para estágio não vigente falha na revalidação e não atribui.

#### BE-02 — Caracterizar convergência com Salomão desligado

Adicionar testes que hoje evidenciem qualquer `safe_noop` órfão:

- `MESSAGE_VERIFY` com IA desligada;
- entrada na rota de IA com Supervisor desligado;
- thread inexistente/404;
- canal sem resposta automática;
- ticket com humano participando;
- ticket já em suporte NOVO e sem owner.

**Gate de saída:** testes de reprodução falham pelo motivo esperado antes da implementação.

### Gate B — Política estrutural de ordenação e ocorrência

#### BE-03 — Introduzir política tipada de efeito

Arquivos previstos:

- `apps/ai_agents/services/lifecycle.py`;
- novo módulo coeso em `apps/webhooks/` ou `apps/ai_agents/services/`, conforme dependências reais;
- `apps/webhooks/services.py`.

Mudanças:

- manter `stale_event` como informação do ledger/projeção;
- classificar o efeito por semântica de domínio;
- permitir somente `PROCESS_IDEMPOTENT_OCCURRENCE` atravessar o cursor stale;
- registrar `projection_skipped=true`, `effect_policy` e `effect_outcome`;
- remover a equivalência atual entre “não atualizar projeção” e “não executar nenhum efeito”.

#### BE-04 — Revalidar ocorrência NOVO

Centralizar no serviço de ciclo/ingestão:

- parse estrito de `entered_at_ms`;
- identidade por conta + ticket + estágio + timestamp provado;
- re-fetch do ticket;
- confirmação de pipeline/estágio/owner;
- criação/reuso idempotente de ciclo;
- enqueue após `transaction.on_commit`;
- resultado tipado: `queued`, `already_processed`, `provider_state_changed`, `owner_present`, `ineligible`, `provider_unavailable`.

Não fabricar timestamp com `timezone.now()` quando o evento calculado contém a ocorrência.

**Gate de saída:** corrida reproduzida passa, snapshot não retrocede e efeitos de IA stale continuam bloqueados.

### Gate C — Separação do Supervisor e convergência humana

#### BE-05 — Criar `SALOMAO_SUPERVISOR_ENABLED`

Arquivos previstos:

- `core/settings/base.py`;
- serviços de rollout/dispatch do Salomão;
- `apps/webhooks/services.py`;
- `apps/webhooks/handlers/hubspot_handler.py`;
- `apps/ai_agents/tasks.py`;
- documentação de variáveis.

Regras:

- a flag deve ser avaliada imediatamente antes de reservar execução da IA;
- API, worker e beat devem reportar o valor efetivo em readiness sem expor secrets;
- mudanças durante uma execução exigem revalidação antes de reply, stage update ou fechamento;
- `false` chama convergência humana, não retorna sucesso silencioso.

#### BE-06 — Criar `SALOMAO_WAITING_RECONCILIATION_ENABLED`

Arquivos previstos:

- `apps/ai_agents/tasks.py`;
- `apps/ai_agents/services/watchdog.py`;
- configuração do beat/readiness.

Regras:

- quando `false`, não chamar Conversations API;
- ainda registrar backlog e motivo de suspensão;
- não atualizar `updated_at` dos itens apenas para rotacionar uma fila desativada;
- não gerar tempestade de 404;
- ao reativar, retomar em batches limitados, com lock e idempotência por `thread_id + message_id`.

#### BE-07 — Serviço único de convergência humana

Arquivos previstos:

- `apps/ai_agents/services/execution.py`;
- serviço de handoff existente ou novo módulo de domínio;
- `apps/ai_agents/tasks.py`;
- integração com `apps/support`.

Regras:

- substituir branches duplicados de fallback;
- validar rota, owner e participação humana;
- fazer handoff idempotente;
- confirmar o estado de suporte NOVO;
- delegar ao Matchmaker sem atribuição direta paralela;
- persistir lifecycle, motivo e auditoria;
- em erro transitório, retry limitado; no esgotamento, estado terminal observável e alerta — nunca órfão silencioso.

**Gate de saída:** matriz de convergência totalmente coberta.

### Gate D — Contrato das subscriptions HubSpot

#### OPS-01 — Documentar e validar responsabilidades

No `judah-webhooks-hsmeta.json`, documentar por teste/artefato:

- `hs_v2_date_entered_939275049`: ocorrência primária do Matchmaker;
- `hubspot_owner_id`: reconciliação/autoridade humana;
- `hs_pipeline_stage`: sinal compartilhado, não requisito único da atribuição;
- `hs_v2_date_entered_939271304`: entrada calculada da rota de IA;
- `conversation.newMessage`: sinal primário de mensagem para o Supervisor;
- `hs_last_message_from_visitor`: sinal calculado auxiliar, nunca identidade de mensagem.

#### OPS-02 — Estado gradual

O hotfix de código deve funcionar com as três subscriptions atualmente inativas.

Após validação local e antes de qualquer reativação:

1. manter `SALOMAO_SUPERVISOR_ENABLED=false`;
2. testar reativação de `hs_pipeline_stage` sem execução da IA;
3. provar que estágio de suporte converge ao Matchmaker e estágio de IA converge ao fallback humano;
4. reativar `hs_v2_date_entered_939271304` somente após a convergência humana estar comprovada;
5. reativar `hs_last_message_from_visitor` apenas como sinal auxiliar idempotente;
6. o rollout posterior do Supervisor reativa a execução por flag, sem novo redesenho de subscriptions.

Cada alteração remota de subscription é um gate operacional separado.

### Gate E — Remediação RLS e privilégios Supabase

#### Evidência atual

As 11 tabelas encontradas estão no schema `public`, sem RLS e sem policies. `anon` e `authenticated` possuem privilégios amplos, incluindo escrita e `TRUNCATE`. O runtime `judah_production_runtime` existe, tem login e atualmente possui `BYPASSRLS`.

Tabelas:

- `conversation_instances`;
- `conversation_events`;
- `conversation_state_transitions`;
- `agent_runs`;
- `tool_call_audit_logs`;
- `availability_reconciliation_leases`;
- `agent_availability_decisions`;
- `assignment_attempts`;
- `support_conversation_cycles`;
- `token_blacklist_blacklistedtoken`;
- `token_blacklist_outstandingtoken`.

#### DB-01 — Inventário de consumidores e matriz de papéis

Antes da migration:

- identificar acessos por Django, Supabase Data API, WebApp, jobs e operadores;
- confirmar `current_user` de API, worker, beat e predeploy;
- verificar `service_role` e rotinas administrativas;
- capturar grants, owners, `rolbypassrls`, policies e dependências;
- provar que nenhum frontend depende de acesso direto a essas tabelas.

#### DB-02 — Migration least privilege

Criar migration Django idempotente e reversível que:

1. revogue todos os privilégios de `anon` e `authenticated` nas 11 tabelas;
2. habilite RLS nas 11 tabelas como defesa em profundidade;
3. não crie policy permissiva para papéis cliente;
4. preserve apenas os privilégios necessários de `judah_production_runtime`;
5. preserve `service_role` somente onde houver consumidor comprovado;
6. não altere owner nem `BYPASSRLS` no mesmo hotfix sem prova de compatibilidade;
7. registre comentários SQL com a justificativa;
8. forneça reverse migration que restaure exatamente o snapshot de grants anterior, sem usar grants genéricos.

RLS não substitui `REVOKE`: como `service_role` e o runtime possuem `BYPASSRLS`, a matriz de privilégios e os triggers de autoridade continuam obrigatórios.

#### DB-03 — Testes PostgreSQL reais

Executar em PostgreSQL local compatível:

- `anon`: SELECT/INSERT/UPDATE/DELETE/TRUNCATE negados;
- `authenticated`: mesmos bloqueios;
- `judah_production_runtime`: operações legítimas do lifecycle e Matchmaker permitidas;
- runtime não autoritativo: triggers existentes continuam bloqueando writes;
- API/worker/beat: smokes de leitura e escrita esperadas;
- token blacklist: emissão, refresh, blacklist e logout;
- migration forward/reverse/forward;
- advisors Supabase sem o alerta crítico nas 11 tabelas.

**Gate de saída:** segurança corrigida sem quebra funcional e sem policy ampla.

### Gate F — Observabilidade, readiness e recuperação

#### OPS-03 — Readiness

Adicionar sinais separados:

- `salomao_supervisor_enabled`;
- `salomao_waiting_reconciliation_enabled`;
- `automatic_assignment_enabled`;
- `hubspot_assignment_signal_recent`;
- `assignment_effect_suppressed_stale` — deve permanecer zero após hotfix;
- `human_fallback_pending`;
- `rls_contract_ready`;
- backlog de ciclos/fila/tentativas sem misturar dívida histórica e falha corrente.

#### OPS-04 — Métricas e alertas

Alertar quando:

- evento NOVO processado não produzir resultado de ocorrência;
- fallback humano não convergir dentro do SLA;
- ticket permanecer em rota de IA com Supervisor desligado;
- watchdog consultar provider com reconciliação desligada;
- evento stale executar efeito não permitido;
- role cliente recuperar acesso às tabelas protegidas.

#### OPS-05 — Dry-run de recuperação

Criar comando somente leitura que classifique candidatos desde o deploy #97:

- ainda NOVO e sem owner;
- já atribuído por humano/outro sistema;
- saiu do NOVO;
- ciclo/tentativa existente;
- ambíguo/quarentena.

O comando não deve:

- replayar webhooks;
- criar ciclos;
- enfileirar;
- alterar owner/stage;
- apagar histórico.

Recovery real será um gate separado, aprovado por lote, revalidando HubSpot imediatamente antes de cada mutação.

### Gate G — Verificação e release

#### V-01 — Qualidade local

Comandos:

```powershell
uv run ruff check .
uv run mypy .
.venv\Scripts\python.exe run_tests_local.py
git diff --check
```

Executar também os testes PostgreSQL reais de RLS/runtime guard.

#### V-02 — Smokes integrados

Cenários mínimos:

1. Salomão desligado + ticket entra na rota IA → handoff → suporte NOVO → Matchmaker → owner humano.
2. Salomão desligado + mensagem nova → nenhuma resposta IA, nenhuma conversa órfã.
3. Salomão ligado + mensagem válida → uma execução/reply.
4. humano assume durante execução → nenhum efeito tardio da IA.
5. owner event chega antes do NOVO calculado → uma atribuição durável.
6. duplicate NOVO → nenhuma duplicidade.
7. Supabase `anon`/`authenticated` sem acesso às 11 tabelas.
8. API/worker/beat operam normalmente com o runtime dedicado.

#### V-03 — Critérios de aceite de produção

- mesmo SHA em `judah`, `judah-worker` e `judah-beat`;
- migrations aplicadas com contrato de grants/RLS confirmado;
- flags efetivas confirmadas nos três serviços;
- subscriptions confirmadas individualmente;
- um ticket real percorre webhook → ciclo → fila → tentativa completed → owner HubSpot;
- um ticket de rota IA converge para humano com Supervisor desligado;
- nenhum novo `assignment_effect_suppressed_stale`;
- nenhum polling de thread quando reconciliação estiver desligada;
- nenhuma regressão de owner, fechamento ou autoridade humana;
- logs e readiness estáveis durante janela de observação.

## 6. Estratégia de rollback

Rollback deve preservar dados e não restaurar exposição de segurança inadvertidamente.

### Código

- desligar `SALOMAO_SUPERVISOR_ENABLED`;
- manter `AUTO_ASSIGNMENT_ENABLED=true` se o protocolo durável estiver saudável;
- se a nova política de ocorrência falhar, desativar somente o novo dispatch por feature flag temporária prevista na implementação e manter ingestão auditável;
- não voltar ao gate global sem registrar backlog dos eventos afetados.

### RLS

- reverse migration restaura o snapshot explícito de privilégios;
- preferir corrigir o papel/policy incompatível em vez de desabilitar RLS;
- rollback de RLS exige decisão operacional explícita, pois reabre exposição;
- nunca executar `DROP`, `TRUNCATE` ou apagar ledger/ciclos/tentativas.

### HubSpot

- subscriptions são revertidas individualmente;
- não desativar todo o app;
- manter o sinal primário `hs_v2_date_entered_939275049` ativo;
- qualquer recuperação de tickets é independente do rollback de código.

## 7. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Processar NOVO realmente obsoleto | re-fetch de pipeline/stage/owner antes de ciclo/fila |
| Duplicar atribuição | identidade da ocorrência + ciclo + tentativa durável |
| IA desligada deixar ticket órfão | serviço único de convergência e alerta de SLA |
| Handoff competir com humano | autoridade humana e owner revalidados sob idempotência |
| RLS bloquear Django | matriz de papéis, PostgreSQL real e rollout forward/reverse |
| `BYPASSRLS` reduzir defesa | `REVOKE`, least privilege e triggers existentes |
| Reativar subscription disparar backlog inesperado | reativação individual, flags off e observação antes do Supervisor |
| Misturar recuperação histórica ao deploy | dry-run e autorização por lote separados |

## 8. Arquivos prováveis

- `apps/webhooks/services.py`
- `apps/webhooks/handlers/hubspot_handler.py`
- `apps/webhooks/tests/test_services.py`
- `apps/webhooks/tests/test_hubspot_handler.py`
- `apps/ai_agents/services/lifecycle.py`
- `apps/ai_agents/services/execution.py`
- `apps/ai_agents/services/watchdog.py`
- `apps/ai_agents/tasks.py`
- `apps/ai_agents/tests/test_lifecycle.py`
- `apps/ai_agents/tests/test_tasks.py`
- `apps/support/conversation_cycle_service.py`
- `apps/support/tasks.py`
- `apps/support/assignment_readiness.py`
- `apps/support/tests/`
- nova migration de segurança no app proprietário das tabelas, dividida por app se necessário
- `core/settings/base.py`
- `docs/setup/environment-variables.md`
- `docs/services/webhooks.md`
- `docs/services/ai_agents.md`
- `docs/operations/absence-safe-assignment.md`
- `hubspot-app/src/app/webhooks/judah-webhooks-hsmeta.json`

O arquivo efetivo de cada alteração deve ser confirmado durante o Gate A. Não criar abstração paralela quando já existir serviço canônico equivalente.

## 9. Definition of Done

- [ ] Corrida de ordenação reproduzida e corrigida por política de domínio.
- [ ] Projeção stale não retrocede lifecycle.
- [ ] NOVO válido nunca é perdido antes do protocolo durável.
- [ ] Salomão e Matchmaker possuem flags/capacidades independentes.
- [ ] Salomão desligado converge para atendimento humano/Matchmaker.
- [ ] Nenhum `safe_noop` deixa conversa órfã.
- [ ] Autoridade humana preservada.
- [ ] Subscriptions documentadas e testadas individualmente.
- [ ] 11 tabelas sem acesso de `anon`/`authenticated`, com RLS habilitado.
- [ ] Runtime Django, worker, beat, auth/token blacklist e recovery continuam funcionais.
- [ ] Ruff, mypy, pytest, PostgreSQL e `git diff --check` aprovados.
- [ ] Dry-run dos candidatos produzido sem mutação.
- [ ] Deploy, subscriptions, flags, migration e recovery executados apenas após seus gates específicos.
- [ ] Smoke real comprova owner HubSpot e tentativa durável.

## 10. Aprovações necessárias

1. **Aprovação do plano:** autoriza apenas implementação local em branch `hotfix/salomao-assignment-flow-isolation`.
2. **Aprovação de PR/push:** separada.
3. **Aprovação da migration Supabase em produção:** separada.
4. **Aprovação de alteração de flags Railway:** separada.
5. **Aprovação de alteração das três subscriptions:** separada.
6. **Aprovação de merge/deploy:** separada.
7. **Aprovação de recovery dos tickets:** separada, por dry-run/lote.
