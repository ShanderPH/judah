# BE-01 — Serviço de domínio do ciclo (Gate A)

**Data:** 21 de julho de 2026
**Escopo:** somente o contrato de domínio, sem schema/migration (Gate B).

## O que foi implementado

Novo módulo `apps/support/conversation_cycle_service.py`, puro e sem I/O,
contendo:

- `parse_stage_entry_timestamp(value)` — normaliza timestamp HubSpot
  (ms-epoch) para UTC aware. Rejeita ausente, não numérico, epoch em segundos
  e valores fora da janela plausível [2000-01-01, 2100-01-01) via
  `InvalidStageTimestampError`. Nunca usa `timezone.now()` ou horário de
  recebimento como substituto.
- `CycleIdentity` (dataclass frozen) — identidade externa imutável:
  `source_system`, `source_account_id`, `hubspot_ticket_id`,
  `entered_stage_at`, `cycle_key`. `source_event_id` não participa da
  identidade (apenas auditoria).
- `build_cycle_key()` — chave versionada `hubspot:v1:<sha256>` sobre a chave
  natural canônica. Determinística e segura para logs (não embute ticket nem
  portal).
- `build_cycle_identity()` — fail-closed: portal ausente
  (`HUBSPOT_PORTAL_ID` não configurado), ticket vazio ou timestamp inválido
  geram `CycleIdentityUnavailableError`.
- `CycleState` + `ACTIVE_CYCLE_STATES` (`queued`, `assigned`,
  `repair_required`) + `TERMINAL_CYCLE_STATES` (`closed`, `cancelled`).
- `CycleClassification` — `created`, `duplicate`, `stale`,
  `active_conflict`, `identity_unavailable`, `repair_required`.
- `classify_cycle_admission(identity, existing)` — decisão determinística e
  fail-closed sobre snapshots já carregados sob lock pelo writer:
  1. mesma chave natural → `duplicate` (retry idempotente, qualquer estado);
  2. ciclo conhecido mais novo → `stale` (evento fora de ordem);
  3. ciclo ativo em `repair_required` → `repair_required` (reconciliação
     explícita obrigatória);
  4. outro ciclo ativo → `active_conflict` (auditável; nunca fecha nem
     substitui implicitamente);
  5. caso contrário → `created`.
- `admit_cycle_occurrence(...)` — fachada sem I/O e sem relógio: converte o
  valor bruto HubSpot, constrói a identidade e classifica. Identidade não
  comprovável retorna `identity_unavailable` (resultado explícito, não
  exceção). Aceita `source_event_id` somente para eco em logs.
- `transition_cycle_state(current, target, reconciliation=False)` — máquina
  de estados do contrato. Estados terminais nunca transitam;
  `repair_required` só sai com `reconciliation=True`; transições fora do
  contrato (incluindo no-op mesmo-estado) lançam
  `InvalidCycleTransitionError`.

Configuração aditiva em `core/settings/base.py`: `HUBSPOT_PORTAL_ID`
(não secreta, default vazio). Vazio = writer fail-closed; leituras não são
afetadas. O valor concreto é decisão pendente do Stop Gate A.

## Limite Gate A/Gate B respeitado

Dependem da tabela física (Gate B, DB-02) e portanto **não** foram
implementados: `SupportConversationCycle`, constraints naturais/parciais, FKs
`cycle_id`, a orquestração `transaction.atomic()` + `select_for_update()` com
releitura após `IntegrityError`, e o dispatch via `on_commit()`. O contrato já
define o ponto de costura: o writer carrega os ciclos conhecidos do ticket sob
lock, chama `classify_cycle_admission()` e só então insere — relendo a chave
natural e retornando `duplicate` quando uma inserção concorrente vencer a
corrida, sem repetir efeito externo. Isso está documentado no docstring do
módulo. Nenhum entrypoint foi alterado; `get_or_create(ticket_id)` permanece
como está até o Gate C (a proibição para novos entrypoints consta no contrato).

## Por que este desenho

- As regras de identidade, classificação e transição são as partes que
  precisam estar corretas e cobertas antes de qualquer migration; isolá-las
  sem I/O torna os testes determinísticos e a revisão humana direta.
- Nenhuma camada nova (repository/factory/interface) foi criada: a codebase
  já concentra regras em módulos de serviço por domínio
  (`durable_assignment_service.py`, `queue_service.py`), padrão seguido aqui.

## Testes

`apps/support/tests/test_conversation_cycles.py` — 45 testes puros (sem DB):
timestamps válidos/inválidos, determinismo e unicidade da chave, fail-closed
de portal/ticket/timestamp, todas as classificações (incluindo precedência de
`stale` sobre `active_conflict` para eventos antigos e `duplicate` em
qualquer estado), todas as transições autorizadas e proibidas, imutabilidade
de estados terminais e reconciliação explícita de `repair_required`.
