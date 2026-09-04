# Master plan — barreira de coorte na abertura

## 1. Resultado pretendido

Quando houver backlog anterior ao início do intervalo operacional atual, o JUDAH deve aguardar por uma
coorte curta e congelada se já existir ao menos um agente `eligible` e outro membro inicial ainda estiver
`stabilizing`. Durante essa espera, nenhuma linha pode ser claimed, nenhuma capacidade pode ser reservada,
nenhum `AssignmentAttempt` pode ser criado e nenhum efeito HubSpot pode ocorrer.

A liberação acontece no primeiro dos eventos:

- todos os membros da coorte deixam `stabilizing`; ou
- o deadline não renovável é atingido.

No deadline, somente agentes individualmente elegíveis e aprovados pelo readback pré-efeito participam do
ranking atual. Agentes incertos permanecem excluídos. Tickets recebidos após a abertura não são bloqueados
pelo backlog antigo.

## 2. Classificação e gates de autoridade

- **Ciclo:** M — hotfix comportamental de produção. A solução adiciona um guard coeso ao protocolo atual;
  não substitui a arquitetura. Se a implementação revelar um refactor arquitetural ou sobreposição
  descontrolada em mais de cinco arquivos de domínio, promover para Ciclo F e pedir nova aprovação.
- **Estado atual:** PLAN. Este documento não autoriza implementação.
- **Autorizações separadas:** implementar; executar integração local; criar migration; commit; push; PR;
  merge; deploy; configuração/flag; ativar shadow; ativar enforcement; recuperação.
- **Pré-aprovação obrigatória:** qualquer teste contra database/Redis não local e qualquer mutação em
  Railway, Supabase, HubSpot ou produção.

## 3. Decisões de desenho fechadas

### 3.1 Janela operacional autoritativa

Adicionar ao resolver nativo de calendário um valor tipado e timezone-aware para o intervalo ativo:
`OperationalWindow(start_at, end_at, timezone_name, source_rule_id)`. A mesma precedência já usada por
`resolve_day()` continua valendo: calendário publicado, ausência/prioridade, fallback legado. Intervalos são
half-open (`start_at <= now < end_at`). Feriado, ausência, calendário degradado ou janela fechada não criam
barreira.

O identificador lógico da barreira é o `start_at` UTC do intervalo atual. Reabertura após almoço ou janela
especial gera outra barreira; virada de timezone/DST é resolvida pelo timezone IANA do calendário.

### 3.2 Backlog protegido e ausência de head-of-line blocking

- **Backlog de abertura:** `entered_queue_at < operational_window.start_at`.
- **Ticket pós-abertura:** `entered_queue_at >= operational_window.start_at`; segue o fluxo atual mesmo
  enquanto a barreira do backlog estiver ativa.
- O drain deve excluir temporariamente os IDs do backlog deferido e continuar o loop para tickets
  pós-abertura, preservando FIFO dentro de cada classe pronta.
- Uma chamada individual para ticket de backlog recebe o mesmo defer; uma chamada individual pós-abertura
  não é bloqueada.

### 3.3 Persistência explícita, sem sobrecarregar falhas/retries

Criar `OpeningAssignmentCohort` como registro operacional durável por `window_started_at`, com:

- UUID, `window_started_at` único, `cohort_observed_at`, `recheck_at`, `deadline_at`;
- `member_agent_ids` (JSON de UUIDs internos, sem PII), contagens iniciais de `eligible`/`stabilizing`;
- estado `active|released`, `release_reason` vazio ou `all_settled|deadline|disabled`;
- `callback_scheduled_at`, `released_at`, `created_at`, `updated_at`.

A migration `0030` deve ser reversível, criar índice somente quando justificado por query, aplicar o mesmo
contrato de proteção/RLS e grants das tabelas operacionais atuais, e ter teste forward/reverse/forward em
PostgreSQL. Não usar cache como fonte de verdade e não reutilizar `failure_code`.

`next_assignment_attempt_at` pode receber `recheck_at` apenas como índice de prontidão da linha; a razão
autoritativa continua na coorte. O defer não incrementa `assignment_attempts`, não preenche
`last_assignment_attempt_at` e não cria `AssignmentAttempt`.

### 3.4 Formação, fechamento e deadline

Na primeira decisão aplicável, usando o relógio do banco e dentro de `transaction.atomic()`:

1. localizar agentes ativos, com identidade, auto-assign e capacidade, cujo snapshot remoto esteja
   `eligible` ou `stabilizing`;
2. exigir simultaneamente ao menos um `eligible` e um `stabilizing`;
3. congelar os IDs desse conjunto; novas chegadas nunca entram como bloqueadoras;
4. definir `cohort_observed_at = max(window_started_at, min(availability_online_since))` para os membros;
   se o dado estiver inconsistente, usar o instante do banco e emitir diagnóstico;
5. calcular `recheck_at` como o maior ETA necessário entre os membros `stabilizing`, isto é,
   `availability_online_since + AVAILABILITY_STABLE_SECONDS`, mais jitter pequeno e limitado;
6. calcular `deadline_at = cohort_observed_at + AVAILABILITY_STABLE_SECONDS +
   SAT_HEARTBEAT_INTERVAL_SECONDS`.

Com defaults atuais, o budget máximo é aproximadamente 60 s desde a primeira observação e o recheck normal
fica próximo de 31–35 s. O deadline persistido nunca é atualizado por chegada tardia, retry ou oscilação.
Se já estiver vencido na criação, não ativar a barreira.

### 3.5 Ponto único de decisão e concorrência

Criar um serviço de domínio pequeno, sem chamadas externas, por exemplo
`opening_cohort_service.py::{evaluate_opening_cohort_barrier, release_opening_cohort}`. Ele retorna resultado
tipado (`not_applicable|shadow_would_defer|deferred|released_all_settled|released_deadline`) e dados de
telemetria limitados.

Integrar o gate a `reserve_next_assignment()` antes de `_verify_candidates()` para evitar readbacks remotos
desnecessários durante a espera e revalidá-lo sob lock imediatamente antes do claim. A criação/leitura da
coorte usa unique constraint + `select_for_update()`; o queue row escolhido também permanece locked. Assim,
drain, webhook individual, retries e chamadas compatíveis passam pela mesma decisão.

Nunca envolver chamada HubSpot em transação. O protocolo atual de reserva, readback, PATCH e finalização
permanece inalterado após a liberação.

### 3.6 Recheck Celery idempotente e fallback

Adicionar `support.task_recheck_opening_assignment_cohort(cohort_id)`:

- carregar por ID e sair em no-op se ausente, released, disabled ou antes/depois de estado aplicável;
- usar o lease/fencing do SAT existente e chamar `sat_heartbeat(force_refresh=True)` como writer único;
- depois chamar o drain normal; nunca duplicar lógica de elegibilidade ou escrever Agent diretamente;
- agendar com `apply_async(eta=recheck_at)` somente em `transaction.on_commit()`;
- marcar `callback_scheduled_at` no registro locked para limitar um callback lógico por coorte;
- tolerar callback duplicado/redelivery; a unique constraint, lock, SAT lease e protocolo de assignment
  tornam a execução idempotente;
- não executar `sleep`; o Beat de heartbeat e o drain de 60 s continuam como safety net.

Falha de publicação após commit não autoriza claim. O Beat deve liberar no deadline. Não criar polling curto
nem uma chamada Users API por ticket.

### 3.7 Configuração e rollout

Usar um único modo validado: `OPENING_COHORT_BARRIER_MODE=off|shadow|enforce`, default `off`. Valor inválido
falha no startup/readiness, em vez de cair silenciosamente em enforcement. `off` é o kill switch próprio e
não altera `AUTO_ASSIGNMENT_ENABLED` nem a elegibilidade individual.

Shadow cria/avalia a decisão e emite métricas, mas não muda prontidão, claim ou efeito. Enforcement só pode
ser configurado após baseline e aprovação separados.

## 4. Invariantes de segurança

1. Gate ativo implica zero claim, capacidade, attempt, PATCH e owner effect.
2. `stabilizing` nunca vira elegível por causa do deadline.
3. Membros e deadline são imutáveis depois da criação.
4. Somente backlog anterior à abertura é deferido.
5. Tickets pós-abertura e atribuição manual explícita não são bloqueados.
6. FIFO e ranking atuais não mudam dentro do conjunto aplicável.
7. Falha de calendário, SAT ou provider é fail-closed para elegibilidade e não renova deadline.
8. Um callback perdido não impede liberação pelo Beat.
9. Callback duplicado não cria segundo efeito.
10. Logs não contêm nome, e-mail, ticket payload, conteúdo ou secret; apenas IDs internos, contagens,
    duração, modo e reason codes limitados.
11. A nova tabela segue least privilege/RLS e roles de runtime existentes.
12. Nenhum replay, reassignment ou alteração HubSpot pertence a este hotfix.

## 5. Sequência test-first e tarefas

### Regra de execução red → green → refactor

Cada tarefa de produção começa somente depois do teste correspondente existir e falhar pela ausência do
contrato esperado, e não por import, fixture ou ambiente quebrado. A ordem por slice é:

| Slice | Vermelho obrigatório | Implementação mínima | Verde/refactor |
|---|---|---|---|
| corrida observada | V-01 | BE-03 gate comum | AC-01/AC-06 |
| calendário | casos V-02 de janela | BE-01 | fronteiras/timezone sem duplicação |
| persistência/locking | casos V-02 + scaffold PostgreSQL V-03 | DB-01 + parte DB de BE-02 | unique/locks/RLS |
| decisão | matriz V-02 | BE-02 | outcomes exaustivos e funções pequenas |
| callback/fallback | casos Celery V-04 preparados | BE-04 | ETA/redelivery/restart/Beat |
| telemetria | asserts de métricas/logs | OBS-01 | cardinalidade/PII/readiness |

Não escrever teste que simplesmente espelhe a implementação. Os asserts devem observar limites do domínio:
estado persistido, número de effects, chamadas externas, relógio, ordem, locks e reason codes.

### Fase 0 — confirmar o cenário antes da solução

#### V-01 — Caracterização e teste vermelho

- **Arquivos previstos:** novo `apps/support/tests/test_opening_cohort_barrier.py`.
- Criar fixture determinística: janela abre, backlog anterior existe, A está `eligible`, B está
  `stabilizing`, ambos têm capacidade.
- Primeiro registrar o comportamento atual: `reserve_next_assignment()` cria attempt/reserva para A.
- Converter para o contrato desejado e capturar o vermelho: outcome `deferred_stabilizing_cohort`, sem claim,
  capacidade, attempt ou chamada HubSpot.
- Repetir via `task_matchmaker_assign_single()` e drain para provar que o gate não pode ficar no wrapper.
- Registrar em `03-verification/V-01-red-scenario.md` o comando, falha esperada e limites históricos.
- **Gate:** nenhuma implementação começa se o vermelho não falhar pelo consumo prematuro esperado.

#### V-02 — Testes de decisão antes do serviço

Escrever a matriz vermelha para:

1. backlog + eligible + stabilizing antes do deadline;
2. todos settled;
3. deadline com membro ainda stabilizing;
4. membro vira away/inativo/sem capacidade;
5. agente novo após congelamento não estende deadline;
6. ticket pós-abertura bypassa;
7. fila vazia não agenda callback;
8. apenas stabilizing, sem eligible, preserva o comportamento atual de no-agent;
9. off/ shadow/ enforce;
10. almoço, feriado, ausência, janela especial, timezone e fronteiras half-open;
11. defer não é falha nem tentativa;
12. backlog e tickets novos coexistem sem head-of-line blocking.

### Fase 1 — contrato de calendário e persistência

#### BE-01 — Expor o intervalo operacional ativo

- **Arquivos:** `apps/support/helpdesk_calendar/service.py` e testes de calendário.
- Extrair um helper tipado reutilizando a resolução atual; não duplicar precedência de regras.
- Manter `resolve_now()` compatível e adicionar testes de timezone/DST/fronteiras.
- **Aceite:** o mesmo instante não pode produzir “aberto” e janela nula; calendário degradado fecha.

#### DB-01 — Persistir a coorte operacional

- **Arquivos:** `apps/support/models.py`, migration `0030_*`, `conftest.py`, testes de migration/RLS.
- Criar o modelo e constraints descritos em 3.3; adicionar cleanup da tabela ao fixture isolado.
- Testar unique race por `window_started_at`, forward/reverse/forward, grants e RLS em PostgreSQL 16.
- **Aceite:** duas transações não criam duas coortes para a mesma janela; reverse não perde outras tabelas.

### Fase 2 — motor de decisão e integração comum

#### BE-02 — Implementar o motor puro da barreira

- **Arquivo:** novo `apps/support/opening_cohort_service.py`.
- Usar dataclasses/enums tipados, funções curtas e reason codes exaustivos.
- Separar resolução de contexto, snapshot da coorte, cálculo de ETA/deadline e transição de estado.
- Não importar cliente HubSpot, task Celery ou wrapper de drain no núcleo da decisão.
- **Aceite:** V-02 fica verde sem mocks de ORM para decisões persistentes.

#### BE-03 — Integrar antes da reserva

- **Arquivos:** `durable_assignment_service.py` e `matchmaker_service.py`.
- Adicionar `ReservationReason.DEFERRED_STABILIZING_COHORT` e
  `QueueItemOutcome.DEFERRED_STABILIZING_COHORT`; não mapear para failure.
- Aplicar fast check e revalidação locked; só depois verificar candidato remoto e executar o protocolo atual.
- Ensinar o drain a continuar para linhas pós-abertura quando o backlog estiver deferido.
- **Aceite:** V-01 fica verde nos caminhos drain e single; nenhum comportamento de ranking muda.

### Fase 3 — coordenação assíncrona e observabilidade

#### BE-04 — Agendar recheck autoritativo

- **Arquivos:** `apps/support/tasks.py`, configuração Celery apenas se exigida pelos testes.
- Criar a task idempotente, agendar após commit e reutilizar `sat_heartbeat(force_refresh=True)` + drain.
- Provar publish somente após commit, rollback sem callback, duplicate delivery no-op e Beat fallback.
- **Aceite:** nenhum `sleep`; no máximo um callback lógico registrado por coorte; redelivery é seguro.

#### OBS-01 — Métricas, logs e readiness

- Emitir `assignment_cohort_barrier_started_total`, `released_total{reason}`,
  `duration_seconds`, contagens initial/final de eligible/stabilizing, backlog protegido,
  `callbacks_total{result}` e `beat_fallback_total`.
- Incluir no readiness: modo, coorte ativa, idade, deadline vencido e backlog ainda deferido.
- Definir dashboards/queries para abertura→primeira atribuição, concentração por agente e transferências em
  2/5 min. Métrica de sucesso recomendada: reduzir transferências humanas em até 2 min sem violar o budget
  p95 de primeira atribuição.
- **Aceite:** cardinalidade limitada e zero PII em teste de captura de logs.

### Fase 4 — provas reais e qualidade

#### V-03 — PostgreSQL 16 concorrente

- Usar `pytest.mark.integration`, `TransactionTestCase`/`transaction=True`, threads com conexões próprias,
  barreiras determinísticas e fechamento de conexão por thread.
- Provar: dois drains, drain + webhook, criação unique da coorte, deadline pelo relógio do DB, lock rollback,
  callback duplicado, um único attempt/efeito e nenhuma capacidade reservada durante o gate.
- Incluir provider fake stateful; não usar SQLite/mocks para alegações de locking.

#### V-04 — Redis 8.6 + worker/Beat Celery reais

- Em stack descartável local, provar ETA curto, lease contention, redelivery, worker restart, callback perdido e
  fallback periódico.
- Inspecionar filas agendadas e logs; afirmar que Users API é reconciliada por coorte, não por ticket.
- Nenhuma credencial real ou endpoint externo é permitido.

#### V-05 — regressão e ferramentas

Executar, nessa ordem, somente após a proteção de database local:

```powershell
uv run python -m common.database_safety
uv run pytest apps/support/tests/test_opening_cohort_barrier.py -vv
uv run pytest apps/support/tests/test_helpdesk_calendar.py apps/support/tests/test_sat_matchmaker.py apps/support/tests/test_durable_assignment_protocol.py apps/support/tests/test_tasks_extended.py -vv
uv run pytest apps/support/tests/test_celery_assignment_integration.py -m integration -vv
uv run ruff check apps/support core/settings conftest.py
uv run mypy apps/support core/settings
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```

O DoD exige cobertura ≥90%, nenhum TODO/FIXME/print, lint/typecheck limpos e todos os critérios deste plano
rastreáveis no relatório de verificação.

## 6. Dependências, caminho crítico e watch list

| Ordem | Tarefa | Depende de | Watch list principal |
|---:|---|---|---|
| 1 | V-01/V-02 | aprovação de implementação | `test_opening_cohort_barrier.py`, testes de calendário |
| 2 | BE-01 | vermelho de janela | `helpdesk_calendar/service.py` |
| 3 | DB-01 | vermelho de persistência | `models.py`, migration `0030`, `conftest.py` |
| 4 | BE-02 | BE-01 + DB-01 | `opening_cohort_service.py` |
| 5 | BE-03 | BE-02 + V-01 | `durable_assignment_service.py`, `matchmaker_service.py` |
| 6 | BE-04 | BE-03 | `tasks.py` |
| 7 | OBS-01 | BE-02..BE-04 | metrics/readiness e testes próprios |
| 8 | V-03/V-04/V-05 | implementação verde focal | somente testes/relatórios |
| 9 | R0..R3 | aprovação por gate | artefatos de deployment, sem mistura com código |

O caminho crítico é V-01/V-02 → BE-01/DB-01 → BE-02 → BE-03 → BE-04 → V-03/V-04/V-05. Trabalho
paralelo só é permitido depois de registrar ownership no `STATUS.md`, sem dois agentes na mesma watch list;
PostgreSQL concorrente e Celery real devem ser serializados quando compartilharem a stack descartável.

## 7. Matriz de aceite

| ID | Cenário | Evidência obrigatória |
|---|---|---|
| AC-01 | backlog + eligible + stabilizing | defer sem claim/attempt/PATCH |
| AC-02 | todos settled | liberação imediata e ranking atual |
| AC-03 | deadline vencido | somente eligible segue; deadline não renova |
| AC-04 | agente tardio | não vira blocker nem estende prazo |
| AC-05 | ticket pós-abertura | não é bloqueado; backlog permanece deferido |
| AC-06 | single + drain concorrentes | mesmo gate, no máximo um efeito |
| AC-07 | callback duplicado/perdido | idempotência e fallback Beat |
| AC-08 | restart/lease contention | fila preservada e conclusão delimitada |
| AC-09 | falha Users API/calendário | fail-closed sem renovar deadline |
| AC-10 | modo off/shadow/enforce | kill switch próprio e shadow sem efeito |
| AC-11 | segurança | RLS/grants, config validada e logs sem PII |
| AC-12 | migração | forward/reverse/forward em PostgreSQL 16 |

## 8. Rollout e stop conditions

### R0 — pré-deploy read-only

- Confirmar SHA e alinhamento API/worker/beat, migrations atuais, roles/RLS, flags SAT, fila e saúde do provider.
- Medir por janela: duração heartbeat, Users API p50/p95/p99, primeira elegibilidade, tamanho do backlog,
  concentração das primeiras atribuições e transferências em 2/5 min.
- Não executar replay nem alterar owner.

### R1 — deploy com modo off

- API primeiro via predeploy/migration; validar history, grants/RLS, readiness e logs.
- Depois alinhar worker e beat no mesmo SHA. Modo continua `off`; nenhum effect novo.

### R2 — shadow

- Aprovação separada para `shadow`; observar no mínimo três aberturas operacionais representativas.
- Comparar `would_defer`, duração projetada e tickets que seriam protegidos com o baseline.

### R3 — enforcement controlado

- Aprovação separada; habilitar somente para backlog de abertura.
- Acompanhar a primeira janela em tempo real até deadline + dois ciclos de Beat.
- Expandir apenas se AC-01–AC-11 permanecerem verificáveis em runtime.

### Stop conditions

Voltar `OPENING_COHORT_BARRIER_MODE=off` e investigar, sem replay automático, se ocorrer:

- coorte ativa após `deadline + 2 * drain_interval`;
- claim/attempt/PATCH durante barreira;
- ticket pós-abertura bloqueado;
- aumento material de erro/latência da Users API;
- p95 abertura→primeira atribuição acima do budget aprovado (default proposto: 60 s);
- divergência de capacidade, duplicate effect ou falha de RLS/readiness.

Rollback de código/migration, alteração de flag e recuperação de fila são operações separadas e requerem
autorização própria.

## 9. Riscos residuais

- O caso histórico não contém snapshot completo de todos os agentes; a prova é sistêmica e prospectiva.
- ETA Celery é acelerador, não garantia; por isso a fonte de verdade é PostgreSQL e o Beat é obrigatório.
- A nova tabela aumenta o escopo de migration/RLS; isso é preferível a esconder estado de domínio em cache ou
  campos de falha, mas exige Gate DB completo.
- `resolve_now()` tem fallback legado; divergência entre calendário publicado e legado deve aparecer na
  telemetria e bloquear enforcement até ser explicada.
- Métrica de transferência depende de definição operacional; usar inicialmente “mudança de owner humano em
  até 2 min” e validar com Produto/Ops antes de declarar sucesso.

## 10. Gate para iniciar implementação

Felipe deve aprovar este plano e, separadamente, autorizar a implementação/migration. A primeira alteração de
código será V-01 (teste vermelho); BE-01/DB-01/BE-02 não começam antes da evidência de reprodução.
