# Research — Calendário Helpdesk

> Data: 2026-08-12
> Escopo desta etapa: pesquisa somente. Nenhuma implementação, migração, deploy, commit ou alteração de contrato foi executada.
> Base: checkout local `judah/webapp`, backend local `judah/apps`, documentação do repositório, guias locais do Next.js e documentação atual consultada via Context7.

## 1. Resumo executivo

O Calendário Helpdesk deve ser tratado como um novo domínio operacional compartilhado entre o painel administrativo, o motor de horário comercial, a triagem, a fila/atribuição e o handoff para atendimento humano. A tela é apenas uma projeção do calendário; a decisão de atendimento precisa ser feita no backend, em um serviço determinístico e reutilizável por webhook, tarefas Celery e endpoints administrativos.

O modelo atual é insuficiente para o requisito completo:

- `BusinessHoursConfig` representa uma única grade semanal, com horas inteiras e sete pares fixos de início/fim.
- `SpecialSchedule` representa uma exceção para uma única data, com horas inteiras ou fechamento, sem recorrência e sem mensagem.
- `business_rules.py` ainda mantém uma grade e feriados hardcoded e também trata a janela especial “Quinta Fire”.
- `request_human_handoff()` escolhe a rota de horário comercial versus fora de horário a partir de `conversation_context.is_off_hours`, mas não consulta um calendário configurável com eventualidade e mensagem personalizada.
- O webapp já possui BFF com allowlist, sessão por cookies HttpOnly, capabilities e padrões HeroUI v3, porém ainda não possui rota, capability, tipo ou item de navegação para calendário.

Recomendação principal: criar um domínio de regras versionável com recorrências e ocorrências materializadas/expandidas por intervalo consultado, mantendo `BusinessHoursConfig` e `SpecialSchedule` como compatibilidade de leitura durante a migração. Não salvar uma cópia de todos os dias do ano como única fonte de verdade; recorrências devem continuar editáveis e auditáveis.

## 2. Evidências da codebase

### 2.1 Frontend

- App Router autenticado em `app/(app)/layout.tsx`; a sessão é resolvida no servidor e a rota é filtrada por `canAccessPath`.
- O shell em `src/components/layout/app-shell.tsx` usa HeroUI, Lucide, Tailwind v4 e GSAP. A navegação é uma lista estática baseada em capabilities.
- `src/lib/api/bff-policy.ts` aplica allowlist de método/caminho, capability, JSON obrigatório para mutações, limite de corpo e verificação de origem. Cada novo endpoint precisa ser incluído explicitamente.
- `src/lib/api/client.ts` usa `cache: "no-store"`, retry somente para GET e `Idempotency-Key` para ações mutáveis. O novo client deve seguir este padrão.
- Os tipos do frontend em `src/types/api.ts` ainda expõem apenas `BusinessHoursResponse` e `SpecialSchedule`; não há contrato para intervalos, recorrências, mensagens rich text ou ocorrências anuais.
- `app/globals.css` importa Tailwind v4 antes de `@heroui/styles`, define tokens Judah em `oklch`, tema claro/escuro e suporte a `prefers-reduced-motion`. O calendário deve usar tokens sem cores cruas e manter alvos de toque estáveis.
- O design system local privilegia cards compostos, estados de loading/error/degraded e animações curtas. A implementação deve evitar overlay teatral ou movimento de toda a grade.

### 2.2 Backend e persistência

Arquivos relevantes no backend:

- `apps/support/models.py`: `BusinessHoursConfig` e `SpecialSchedule`.
- `apps/support/api.py`: `GET /support/business-hours/`, listagem/criação/remoção de `special-schedules`.
- `apps/support/schemas.py`: schemas Ninja atuais usam campos de hora inteira e `Literal`/validadores Pydantic.
- `apps/ai_agents/utils/business_rules.py`: timezone `America/Sao_Paulo`, feriados hardcoded, `is_business_hours()` e `off_hours_reason()`.
- `apps/ai_agents/services/execution.py`: `request_human_handoff()` escolhe pipeline/stage e mantém idempotência da operação externa.
- `apps/ai_agents/tasks.py`: tarefa Celery hidrata contexto HubSpot e reexecuta handoff com retry.
- testes existentes cobrem horário, exceções, autorização e auditoria administrativa; devem ser estendidos, não substituídos.

Limitações do contrato atual:

1. Horas inteiras não permitem `09:30`, pausas, múltiplos intervalos por dia ou precisão consistente de fechamento.
2. O nome “mensal” e “anual” do requisito não cabe em uma exceção diária simples.
3. Uma ausência precisa de intervalo de datas/horas, regra de recorrência, mensagem e precedência; `SpecialSchedule.reason` não é um substituto seguro para isso.
4. Não existe hoje uma resolução única que retorne “aberto”, “fechado”, “motivo”, “mensagem”, “intervalos efetivos” e “versão da regra”.
5. Alterações administrativas já usam `execute_audited_action`; o novo domínio deve preservar autenticação manager/admin, idempotência e trilha de auditoria.

### 2.3 Integração operacional

Fluxo atual simplificado:

```text
HubSpot webhook / tarefa AI
  -> business_rules.is_business_hours / off_hours_reason
  -> triagem e ConversationContext.is_off_hours
  -> request_human_handoff()
  -> pipeline/stage de horário comercial ou fora de horário
  -> webhook/worker de admissão na fila
```

Fluxo alvo:

```text
evento HubSpot ou tentativa de handoff
  -> ScheduleResolver(now, timezone, contexto)
  -> decisão efetiva: OPEN | CLOSED | ABSENCE | CUSTOM
  -> triagem usa a mesma decisão
  -> handoff usa a mesma decisão e mensagem versionada
  -> HubSpot recebe rota apropriada e, quando aplicável, mensagem de ausência
```

A resolução deve acontecer no backend no momento da decisão, em timezone configurado, e não confiar em um booleano calculado anteriormente. Deve existir proteção contra divergência entre o horário enviado pelo webhook e o horário reavaliado pelo worker.

## 3. Modelo de domínio recomendado

### 3.1 Entidades

Proposta inicial, a confirmar no Planning:

- `HelpdeskSchedule`: configuração publicada, timezone, nome, status, versão e auditoria.
- `HelpdeskScheduleRule`: regra de atendimento ou ausência, tipo `service`/`absence`, recorrência `once`/`weekly`/`monthly`/`yearly`, prioridade, vigência e status.
- `HelpdeskScheduleInterval`: dia da semana/data padrão, `start_time`, `end_time`, permitindo múltiplos intervalos e `end_time` exclusivo.
- `HelpdeskAbsenceMessage`: conteúdo estruturado da mensagem, formato permitido, versão e status; o contrato de envio deve ser separado do HTML apresentado no editor.
- Opcional: `HelpdeskScheduleOccurrence` materializada apenas para exceções/consultas ou para uma janela de cache, com `source_rule_id`, data, intervalos e hash da versão.

Todos os writes devem ser transacionais, idempotentes e auditados. Restrições devem impedir intervalo invertido, sobreposição ambígua na mesma prioridade e recorrência sem parâmetros válidos.

### 3.2 Semântica de recorrência

- **Individual:** uma data específica; intervalos definidos naquele dia.
- **Semanal:** dias selecionados da semana e vigência opcional; intervalos podem variar por dia.
- **Mensal:** o requisito precisa de uma decisão explícita: “repete nos dias da semana do mês” ou “repete em uma semana-modelo”. Recomenda-se persistir a primeira forma, com `week_of_month` opcional, para evitar ambiguidade.
- **Anual:** dias da semana recorrentes ao longo do ano ou datas selecionadas no modal anual. O cadastro anual de eventualidade deve persistir seleção de datas/regra, não apenas pixels/checks da UI.

Precedência sugerida para o mesmo instante: ausência explícita > fechamento especial > horário de atendimento específico > regra semanal/mensal/anual > configuração padrão. Empates devem ser rejeitados no write ou resolvidos por prioridade explícita, nunca por ordem incidental do banco.

### 3.3 Mensagem de ausência

O editor deve suportar negrito e emojis, mas o backend deve armazenar um formato seguro e provider-neutral. A opção preferida é um documento limitado (por exemplo, JSON rich text com nós permitidos) e uma renderização HubSpot específica na borda de integração. Não aceitar HTML arbitrário nem interpolação de dados sem escaping/sanitização. O contrato deve definir fallback de texto puro para canais que não suportem formatação.

## 4. Arquitetura de API sugerida

Manter a API Ninja tipada e protegida por `require_manager_or_admin`:

- `GET /support/helpdesk-calendar/?from=YYYY-MM-DD&to=YYYY-MM-DD&view=month|week`
- `GET /support/helpdesk-calendar/rules/`
- `POST /support/helpdesk-calendar/rules/`
- `PATCH /support/helpdesk-calendar/rules/{id}/`
- `DELETE /support/helpdesk-calendar/rules/{id}/`
- `POST /support/helpdesk-calendar/preview/` para validar conflitos antes de publicar.
- `GET /support/helpdesk-calendar/resolve/?at=...` para diagnóstico interno/read-only, se necessário.
- `GET /support/helpdesk-calendar/messages/` e mutation da mensagem dentro do fluxo de eventualidade, evitando duplicidade de source of truth.

As respostas devem separar `rules` de `occurrences`, incluir timezone, versão/publication state, origem/prioridade da ocorrência, intervalos efetivos e motivo/mensagem. Listagens grandes devem usar paginação ou janela limitada; a grade mensal/semanal deve pedir somente o intervalo visível.

No BFF/frontend, cada path precisa de allowlist em `src/lib/api/bff-policy.ts`, capability nova (por exemplo `support.calendar.read` e `support.calendar.manage`) e métodos tipados em `client.ts`/`server-dal.ts`. Mutations exigem JSON, origem confiável e `Idempotency-Key`.

## 5. UX e design system

Estrutura recomendada:

1. Cabeçalho “Calendário Helpdesk”, timezone visível, status efetivo agora e ações “Nova campanha”/“Nova eventualidade”.
2. Toggle Mensal/Semanal, navegação de período e botão “Hoje”.
3. Grade mensal com cards/ células selecionáveis; cada dia mostra estado aberto/fechado/ausência, intervalos compactos e indicadores de múltiplas regras.
4. Visão semanal com colunas por dia e escala de intervalos; no mobile, rolagem horizontal contida e célula selecionada acessível.
5. Painel/modal do dia com fonte da regra, intervalos efetivos, conflitos e ações de editar/remover.
6. Wizard de campanha/eventualidade com passos: tipo, vigência/recorrência, horários por dia, mensagem (apenas eventualidade), revisão e publicação.
7. Modal anual com seleção de datas, resumo de quantidade e “limpar seleção”; deve ter labels, teclado, foco retornável e não depender apenas de cor/check visual.

HeroUI v3 atual usa composição explícita e React Aria: `Calendar.Header/Grid/GridBody/Cell`, `DatePicker` com `DateField` e `Calendar`, `Modal.Backdrop/Container/Dialog`, e `TextField`/`TextArea`/`TimeField`. Usar `onPress` onde o componente HeroUI expõe interação, não padrões v2 como `HeroUIProvider` ou props flat. O calendário de negócio pode usar `Calendar` para seleção, mas a grade mensal/semanal de operação provavelmente será uma composição própria sobre `Card`/`Button` para exibir intervalos e seleção por dia.

GSAP deve limitar-se a entrada curta do painel ou mudança de seleção, sempre com `matchMedia`/reduced motion. Não aplicar animação em cada célula durante navegação de mês.

## 6. Segurança, consistência e observabilidade

- Autorizar no backend por capability/role; esconder menu no frontend não é controle de acesso.
- Registrar `AdministrativeActionAudit` para criar, editar, publicar, desativar e excluir regra/mensagem, incluindo idempotency key e versão afetada.
- Não enviar HTML bruto, tokens ou conteúdo integral de erro HubSpot para logs.
- Usar transação e optimistic concurrency (`version`/`updated_at`) para impedir que dois administradores sobrescrevam uma publicação.
- Resolver com timezone IANA; persistir instantes em UTC quando houver datetime e preservar timezone de negócio na configuração.
- Definir comportamento fail-closed: se o calendário não puder ser resolvido no caminho de handoff, não atribuir silenciosamente a humano como se estivesse aberto; manter fallback operacional explícito e observável.
- Expor métricas/logs estruturados para decisão, regra vencedora, conflito, fallback, envio/supressão de mensagem e latência.

## 7. Testes e verificação necessários

Backend:

- unidade para limites `[start, end)`, timezone/DST, dia sem intervalo, múltiplos intervalos e precedência;
- recorrências semanal/mensal/anual, datas bissextas e virada de ano;
- conflito/overlap rejeitado e preview idempotente;
- autorização viewer/agent/manager/admin e auditoria/idempotency;
- integração de triagem/handoff: aberto, fora de horário, eventualidade, mensagem rich text sanitizada, retry sem duplicar mensagem/rota;
- migração PostgreSQL 16 e compatibilidade temporária com os modelos atuais.

Frontend:

- reducer/normalização de ocorrências e navegação de mês/semana;
- estados loading, erro, degraded e vazio;
- seleção por teclado, foco, labels, contraste, mobile e reduced motion;
- validação de formulário e prevenção de double-submit;
- BFF allowlist, capability e contratos dos métodos client.

Verificação final deve incluir lint, typecheck, testes unitários/integrados, build, `git diff --check`, browser autenticado e smoke staging. Testes que conectem a banco não-local exigem aprovação explícita conforme `AGENTS.md`.

## 8. Riscos e decisões pendentes para Planning

1. Definir se o calendário controla a disponibilidade geral do helpdesk, a elegibilidade de agentes ou ambos. A recomendação é: calendário controla a operação do helpdesk; disponibilidade individual continua no domínio de agentes.
2. Definir a semântica exata de “mensal” e “anual” e a precedência de uma regra de serviço sobre ausência.
3. Confirmar o contrato de mensagens da HubSpot: endpoint, formato rico aceito, limite de tamanho e se a mensagem deve ser enviada imediatamente ou somente anexada ao handoff.
4. Decidir compatibilidade/migração de `BusinessHoursConfig`, `SpecialSchedule` e feriados hardcoded; não remover os legados até haver paridade comprovada.
5. Definir capacidade/capabilities para leitura e gestão. A proposta é manter leitura de calendário com `support.admin.read` inicialmente e criar `support.calendar.manage` para mutations, sujeito à matriz RBAC.
6. Confirmar se o branch de implementação será `feat/helpdesk-calendar` e qual gate de aprovação será usado no `ai-system/requests/`.

## 9. Referências consultadas

- Código local: `apps/support/models.py`, `apps/support/api.py`, `apps/support/schemas.py`, `apps/ai_agents/utils/business_rules.py`, `apps/ai_agents/services/execution.py`, `apps/ai_agents/tasks.py`.
- Código local webapp: `app/(app)/layout.tsx`, `src/components/layout/app-shell.tsx`, `src/lib/api/bff-policy.ts`, `src/lib/api/client.ts`, `src/lib/auth/access-policy.ts`, `src/types/api.ts`, `app/globals.css`.
- Documentação local do Next.js instalada em `node_modules/next/dist/docs/`, especialmente Server and Client Components, Route Handlers e Caching.
- Next.js oficial via Context7: https://github.com/vercel/next.js/tree/canary/docs
- HeroUI v3 via Context7: https://www.heroui.com/en/docs/react/migration/calendar, https://www.heroui.com/en/docs/react/migration/date-picker, https://www.heroui.com/en/docs/react/migration/modal
- Django Ninja via Context7: https://github.com/vitalik/django-ninja/tree/master/docs/docs

## 10. Gate de saída

Research concluída em modo read-only. O próximo passo autorizado é produzir `docs/planning/helpdesk-calendar-plan.md` com decisões fechadas, tarefas BE/DB/FE/INT/OPS, contratos, migração, critérios de aceitação, rollback e gates de verificação. Implementação, branch, commit, deploy e mutações externas permanecem bloqueados até aprovação explícita do Planning.
