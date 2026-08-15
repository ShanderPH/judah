# Planning — Calendário Helpdesk

## Addendum — separação de execução e dependência backend

Status efetivo: frontend implementado parcialmente em `C:\Projetos Febrate\judah\webapp`; backend pendente no repositório pai `C:\Projetos Febrate\judah`.

O backend é obrigatório para fechar esta feature. A UI depende de persistência, resolução de recorrências, precedência, auditoria, optimistic concurrency e integração real com triagem/handoff. O wizard atualmente cobre apenas o cadastro inicial de uma regra `once`; não representa sozinho a implementação completa planejada.

### Pacote backend a executar em `C:\Projetos Febrate\judah`

1. **DB-01:** criar `HelpdeskSchedule`, `HelpdeskScheduleRule`, `HelpdeskScheduleInterval` e `HelpdeskAbsenceMessage` em `apps/support/models.py`, com migration reversível, constraints, índices e compatibilidade temporária com `BusinessHoursConfig`/`SpecialSchedule`. Não executar DROP/TRUNCATE nem aplicar em banco não-local.
2. **BE-01:** criar `apps/support/helpdesk_calendar/service.py` e schemas Ninja explícitos. O resolver deve tratar timezone/DST, recorrência `once`/`weekly`/`monthly`/`yearly`, precedência de ausência, intervalos `[start, end)`, conflito, versão e fallback fail-closed; preservar os wrappers de `business_rules.py`.
3. **BE-02:** implementar em `apps/support/api.py` ou router dedicado os endpoints de calendário, regras, preview e resolve. Usar `require_manager_or_admin`, `execute_audited_action`, idempotência e `expected_version`; retornar o contrato consumido pelo WebApp.
4. **INT-01:** integrar a resolução na triagem, `request_human_handoff()` e worker, reavaliando no instante da ação. Separar rota de mensagem, garantir idempotência por efeito externo e confirmar o contrato real de mensagem da HubSpot antes de implementar o envio rich text/fallback plain text.
5. **V-01 backend:** adicionar testes para limites, recorrências, DST, precedência, overlap, RBAC, auditoria, idempotência e handoff. Executar `.venv\Scripts\python.exe run_tests_local.py` no repositório pai; qualquer teste contra banco não-local exige aprovação explícita.

### Estado do pacote frontend

Já implementado no `webapp`: rota `/calendar`, navegação/capability, contratos TypeScript, client API, allowlist BFF, visão mensal/semanal, painel do dia, wizard inicial e testes locais. Após o backend, ainda será necessário validar os contratos reais, completar recorrências/edit/delete/preview, browser autenticado e integração ponta a ponta.

### Próxima ação

Executar DB-01 e BE-01 no diretório pai. Não considerar a feature concluída, nem habilitar enforcement/deploy, até BE-02, INT-01 e os gates de verificação passarem.

> Status: DRAFT — aguardando aprovação explícita para Implementing
> Research: `docs/research/helpdesk-calendar.md`
> Branch proposta: `feat/helpdesk-calendar`
> Escopo: backend Django/Ninja, PostgreSQL/Supabase, regras de triagem/handoff, BFF e UI Next.js/HeroUI.

## 1. Objetivo

Entregar um calendário administrativo mensal/semanal para controlar horários de atendimento e eventualidades recorrentes, com uma única resolução de disponibilidade usada pela UI, triagem, fila/atribuição e handoff humano. A eventualidade deve poder enviar uma mensagem de ausência segura e formatada via HubSpot.

## 2. Premissas adotadas

- `America/Sao_Paulo` permanece o timezone inicial, mas o modelo aceita timezone IANA.
- “Mensal” significa repetição em dias da semana dentro da vigência mensal; `week_of_month` será opcional para representar uma semana específica.
- “Anual” aceita regra recorrente e seleção explícita de datas para eventualidades.
- A ausência tem precedência sobre horário de atendimento.
- O calendário controla o estado operacional do helpdesk; disponibilidade/capacidade individual de agentes continua em `Agent`/SAT.
- `BusinessHoursConfig`/`SpecialSchedule` não serão removidos nesta feature; haverá compatibilidade de leitura/migração e remoção posterior em tarefa separada.
- Apenas manager/admin poderão gerenciar regras; leitura seguirá `support.admin.read` no primeiro corte. Se a matriz confirmar capability dedicada, ela será adicionada antes das mutations.

## 3. Arquitetura alvo

### 3.1 Backend/DB

Criar no app `support`:

- `HelpdeskSchedule` — configuração publicada, timezone, status, versão, timestamps.
- `HelpdeskScheduleRule` — tipo (`service`/`absence`), recorrência, vigência, prioridade, status, nome e origem.
- `HelpdeskScheduleInterval` — weekday/date, start/end como `TimeField`, vínculo à regra.
- `HelpdeskAbsenceMessage` — documento rich text restrito, texto puro fallback, status/version.
- `ScheduleResolution` como value object/TypedDict, não necessariamente tabela: estado, intervalos, reason, message, source rule/version.

Adicionar índices por `active`, vigência, tipo, prioridade, data e weekday. Usar constraints/validação para intervalos crescentes, parâmetros válidos por recurrence e unicidade de publicação. A migration deve ser reversível e não executar DROP/TRUNCATE.

### 3.2 Serviço de resolução

Criar serviço puro e testável, por exemplo `apps/support/helpdesk_calendar/service.py`:

1. normalizar instantâneo para timezone da configuração;
2. carregar regras ativas que cobrem a data;
3. expandir a recorrência para o dia consultado;
4. ordenar por precedência e prioridade;
5. calcular intervalos efetivos com semântica `[start, end)`;
6. retornar decisão estruturada e versão;
7. falhar de modo observável/fail-closed quando a fonte não puder ser resolvida.

`apps/ai_agents/utils/business_rules.py` deve delegar para o serviço, preservando wrappers públicos (`is_business_hours`, `off_hours_reason`) para reduzir regressão. Feriados hardcoded serão convertidos em regras/seed compatíveis somente após paridade testada.

### 3.3 Handoff/triagem

- Reavaliar o calendário no worker, no instante da ação, não somente no webhook.
- Popular `ConversationContext.is_off_hours` e metadados com `schedule_resolution`.
- Ajustar `request_human_handoff()` para usar a decisão efetiva e incluir a mensagem de ausência quando o estado for `ABSENCE`/`CLOSED`.
- Manter idempotency key incluindo instance, ticket, turn, pipeline/stage e versão da regra.
- Separar “rotear para pipeline/stage fora do horário” de “enviar mensagem”: cada efeito externo deve ter auditoria/idempotência própria.
- Se HubSpot não suportar o formato rich text definido, enviar fallback de texto puro e registrar a degradação.

## 4. API e BFF

### 4.1 Endpoints Django Ninja

- `GET /support/helpdesk-calendar/?from=&to=&view=`: janela de ocorrências resolvidas.
- `GET /support/helpdesk-calendar/rules/`: regras paginadas/filtradas.
- `POST /support/helpdesk-calendar/rules/`: criar regra.
- `PATCH /support/helpdesk-calendar/rules/{id}/`: editar com `expected_version`.
- `DELETE /support/helpdesk-calendar/rules/{id}/`: desativar/excluir de acordo com política.
- `POST /support/helpdesk-calendar/preview/`: validar conflitos e retornar ocorrências sem publicar.
- `GET /support/helpdesk-calendar/resolve/`: diagnóstico read-only de um instante, protegido e sem conteúdo sensível.

Schemas devem ser explícitos, sem `dict` solto: enums/literals para tipo e recorrência, `datetime.time` para intervalos, `date`/timezone IANA validados, rich text com tamanho/nós permitidos, respostas com `occurrences`, `rules`, `timezone`, `version` e `degraded`.

### 4.2 Webapp

- adicionar capability(s) e `/calendar` em `src/lib/auth/access-policy.ts`;
- adicionar item de navegação no `AppShell`;
- incluir cada método no `src/lib/api/bff-policy.ts`;
- adicionar contratos a `src/types/api.ts` e métodos tipados ao `client.ts`/`server-dal.ts`;
- usar `cache: no-store` para estado operacional e abortar requests ao trocar de período;
- usar `Idempotency-Key` e confirmação para mutations destrutivas/despublicação.

## 5. Implementação frontend

Arquivos/features planejados:

- `app/(app)/calendar/page.tsx`: route server-authenticated mínima.
- `src/features/helpdesk-calendar/helpdesk-calendar-view.tsx`: estado de período/view/seleção.
- `src/features/helpdesk-calendar/calendar-grid.tsx`: grade mensal/semanal acessível.
- `src/features/helpdesk-calendar/rule-wizard.tsx`: campanha/eventualidade.
- `src/features/helpdesk-calendar/annual-date-picker.tsx`: seleção anual.
- `src/features/helpdesk-calendar/calendar-utils.ts`: tipos, agrupamento, precedência visual e validação client-side.

Usar HeroUI v3 composto (`Calendar`, `DatePicker`, `Modal`, `TextField`, `TextArea`, `TimeField`, `Button`, `Card`) e `onPress`. A grade operacional poderá ser customizada quando o `Calendar` não suportar a densidade de conteúdo, mantendo semântica ARIA e foco. Não introduzir `HeroUIProvider`, APIs v2 ou framer-motion. GSAP somente em transições curtas e com reduced motion.

Estados obrigatórios: loading skeleton, erro recuperável, resposta degradada, vazio, conflito de regra, salvamento, sucesso e falha pós-salvamento. Mobile deve manter leitura por lista/scroll horizontal contido.

## 6. Sequência de tarefas

### DB-01 — Modelo e migration

Criar modelos, constraints, índices e migration reversível; confirmar SQL gerado e compatibilidade PostgreSQL 16. Não aplicar em banco não-local nesta etapa.

### BE-01 — Schemas e service de resolução

Implementar schemas Ninja, normalização de recorrência, resolver puro, precedência, conflitos e compatibilidade com funções antigas.

### BE-02 — API administrativa e auditoria

Implementar list/create/update/deactivate/preview/resolve com `require_manager_or_admin`, `execute_audited_action`, idempotência e optimistic concurrency.

### INT-01 — Triagem, handoff e HubSpot

Integrar resolução no caminho de handoff/worker, mensagem de ausência provider-neutral, fallback plain text, idempotência e logs estruturados. Confirmar contrato real da HubSpot antes do código de envio.

### FE-01 — BFF, tipos e data access

Adicionar policies, capability, contratos TypeScript, client/server DAL e testes de allowlist.

### FE-02 — Calendário mensal/semanal

Construir visão de agenda, navegação, seleção de dia, painel de intervalos, estado atual e responsividade.

### FE-03 — Wizards e anualidade

Construir formulários de campanhas/eventualidades, editor seguro, seleção anual, preview, conflitos e confirmação.

### V-01 — Testes e documentação

Adicionar testes backend/frontend, atualizar README/contratos/runbook e produzir `HANDOFF.md`/`STATUS.md` no request do `ai-system`.

## 7. Critérios de aceitação

- Administrador visualiza mês e semana no timezone configurado e seleciona um dia para ver intervalos efetivos.
- Campanhas individual, semanal, mensal e anual podem ser criadas, editadas, desativadas e visualizadas sem duplicação ambígua.
- Eventualidades suportam seleção individual, semanal, mensal e anual, com mensagem editável, negrito e emojis via formato seguro.
- Precedência é determinística e exibida no painel/preview.
- A mesma resolução é usada por triagem e handoff, incluindo reavaliação no worker.
- Fora de horário/eventualidade roteia conforme configuração e envia uma única mensagem idempotente, com fallback documentado.
- Viewer/agent não conseguem gerenciar; manager/admin passam por auditoria.
- Não há acesso direto do browser a Supabase/HubSpot nem segredo em bundle/log.
- Lint, typecheck, testes, build, diff check, browser autenticado e smoke staging passam nos gates aplicáveis.

## 8. Estratégia de testes

Backend: `pytest` focado em resolver, recorrência, timezone/DST, constraints, API, RBAC/auditoria e handoff. Depois suite isolada local com PostgreSQL/Redis conforme launcher do projeto.

Frontend: Vitest para utils, reducer, schemas e BFF; `npm run lint`, `npm run typecheck`, `npm run build`; browser sub-agent para mês/semana, modal, teclado, mobile, tema e reduced motion.

Integração: ambiente staging somente em gate separado e com aprovação; validar HubSpot real sem inferir sucesso a partir de readiness ou build.

## 9. Rollback e rollout

- Feature flag para leitura e enforcement do novo resolver separadamente.
- Primeiro deploy com shadow/read-only resolver e métricas de divergência contra `business_rules` legado.
- Habilitar mutations administrativas depois de migration e autorização verificadas.
- Habilitar enforcement no handoff somente após teste de ticket controlado e confirmar rota/mensagem no HubSpot.
- Rollback de código mantém tabelas novas; desligar flag retorna ao resolver legado. Migração down só após confirmar que não há regras novas dependentes.

## 10. Gate de aprovação

Este documento está pronto para revisão, mas não autoriza implementação, criação de branch, migração, commit, push, deploy ou chamadas externas mutáveis. Para avançar, aprovar explicitamente o Planning e confirmar os quatro pontos: semântica mensal/anual, contrato de mensagem HubSpot, capability de gestão e branch proposta.
