# Research — Helpdesk Calendar e triagem nativa

> Data: 2026-08-15
> Fase: Research, somente leitura sobre GitHub, Railway e produção
> PR analisado: [#105 — feat(ai): migrar triagem Heimdall para o backend](https://github.com/ShanderPH/judah/pull/105)

## 1. Resultado executivo

O PR #105 foi mergeado em `main` no commit `488eeecf02b5191e78ce33c73725fa4949ef25f9` e esse mesmo SHA está implantado com sucesso nos serviços Railway `judah`, `judah-worker` e `judah-beat`. O health check público respondeu HTTP 200 e a leitura filtrada dos logs recentes não encontrou erro, warning, exception ou traceback relacionado a triagem, calendário ou handoff.

O PR moveu a triagem Heimdall para o backend e tornou o horário de atendimento uma decisão de runtime, reavaliada no worker. Porém, a autoridade implantada ainda é o domínio legado `BusinessHoursConfig`/`SpecialSchedule` exposto por `apps.support.agent_sync_service.is_business_hours()`. A implementação local iniciada do novo calendário criou um domínio mais rico, mas ainda está não versionada e baseada no `main` anterior ao PR #105. A integração correta precisa preservar simultaneamente a identidade, os confidence gates, o lifecycle e a idempotência introduzidos pelo PR #105 e a resolução detalhada do calendário.

## 2. Fontes analisadas

- Pesquisa e plano anteriores:
  - `webapp/docs/research/helpdesk-calendar.md`;
  - `webapp/docs/planning/helpdesk-calendar-plan.md`.
- Código local não commitado do calendário:
  - `apps/support/helpdesk_calendar/`;
  - modelos, schemas, API e migration `0028`;
  - integração em `business_rules`, webhook, worker, handoff e WebApp;
  - testes backend e frontend.
- PR #105 via GitHub CLI:
  - descrição, commits, arquivos, plano, handoff e matriz N8N → JUDAH;
  - diff entre `620df8e` e `488eeecf`.
- Produção via Railway CLI, somente leitura:
  - serviços, deploys, SHA, status, domínio e logs recentes;
  - health check `https://judah-production.up.railway.app/api/v1/health/`.
- Documentação atual:
  - Next.js 16, via Context7 e docs locais instaladas;
  - Railway CLI, via Context7;
  - HubSpot Conversations/Custom Channels, via Context7;
  - HeroUI v3 `Modal`, `Card` e `Button`, via skill oficial do projeto.
- Memória de execução local de 2026-08-12, usada apenas como histórico e depois confrontada com o checkout atual.

## 3. Estado confirmado do PR #105 e produção

### 3.1 GitHub

- PR: `#105`, estado `MERGED`.
- Merge: `2026-08-15T15:13:42Z`.
- Merge commit: `488eeecf02b5191e78ce33c73725fa4949ef25f9`.
- Mudanças relevantes:
  - resolução determinística de identidade do cliente;
  - lifecycle `CONTACT_REQUIRED`/`CONTACT_COLLECTING`;
  - gates de confiança e de identidade para rotas sensíveis;
  - execução Heimdall nativa sem dependência obrigatória do N8N/Salomão externo;
  - reavaliação de horário comercial no worker;
  - efeitos HubSpot auditados e idempotentes;
  - atualização auditada do estágio de espera;
  - pacote de handoff enriquecido sem PII bruta.

### 3.2 Railway

- Ambiente: `production`.
- API `judah`: deploy `SUCCESS`, instância `RUNNING`, SHA `488eeecf`.
- Worker `judah-worker`: deploy `SUCCESS`, instância `RUNNING`, SHA `488eeecf`.
- Beat `judah-beat`: deploy `SUCCESS`, instância `RUNNING`, SHA `488eeecf`.
- Redis 8.6.2: instância `RUNNING`.
- Health check: HTTP 200.
- Logs filtrados da API e worker: nenhum sinal de erro no recorte consultado.

Limitação: a leitura não executou tickets reais nem mutações HubSpot. Portanto, confirma disponibilidade e alinhamento de SHA, mas não comprova ainda o comportamento de uma eventualidade em WhatsApp/webchat.

## 4. Análise de integração

### 4.1 Autoridades de horário concorrentes

Hoje há três caminhos:

1. `apps.support.agent_sync_service.is_business_hours()` — usado pelo PR #105 no dispatcher e no worker; considera `SpecialSchedule`, feriados, Quinta Fire e `BusinessHoursConfig`.
2. `apps.ai_agents.utils.business_rules` — usado por webhooks e código legado.
3. `apps.support.helpdesk_calendar.service.resolve_now()` — implementação local nova, com regra vencedora, mensagem, prioridade e intervalos.

Manter os três como autoridades independentes criaria divergência entre a tela, a triagem e o handoff. O alvo deve ser `resolve_now()` como autoridade única, com adapters legados delegando a ele e fallback estritamente transitório quando a migration/tabela ainda não estiver disponível.

### 4.2 Conflito de base com o PR #105

O checkout local começou em `620df8e`, enquanto produção está em `488eeecf`. Aplicar diretamente os arquivos locais sobre `origin/main` removeria partes do PR #105, especialmente identidade, lifecycle e confidence gates. A integração deve partir de `origin/main` e portar somente as alterações do calendário, resolvendo os arquivos sobrepostos para manter os dois contratos.

### 4.3 Reavaliação no worker

O PR #105 já reavalia `is_off_hours` no início da task Celery. Essa proteção deve ser preservada, mas a task deve obter um snapshot estruturado do novo resolver, não apenas um booleano. O mesmo snapshot precisa entrar em `ConversationContext` e ser reavaliado antes do handoff, evitando mensagem ou rota baseada em informação obsoleta.

### 4.4 Mensagem de ausência

O código HubSpot já possui um renderer de Markdown limitado que:

- escapa HTML bruto;
- suporta elementos seguros e links validados;
- produz `richText` HTML;
- envia também o campo obrigatório `text`.

A documentação atual do HubSpot confirma que mensagens de custom channel usam `text` obrigatório e `richText` opcional, respeitando as capabilities registradas pelo canal. A mesma documentação alerta que o envio por Conversations API não é suportado para uma conta WhatsApp Business nativa conectada ao HubSpot. Assim, webchat/custom channel pode usar o payload implementado; para WhatsApp nativo, a mensagem provider-neutral e seu fallback plain text estão prontos, mas o transporte existente precisa ser comprovado em staging ou substituído por um mecanismo oficialmente suportado. A idempotência existente de `send_reply_with_audit` continua sendo a barreira contra duplicidade.

## 5. Falhas e melhorias da tela `/calendar`

### 5.1 Status rail global

`AppShell` sempre reserva a coluna `320px` e sempre renderiza `StatusRail`, inclusive em `/calendar`. O componente já é client-side e usa `usePathname`; a correção mais coesa é condicionar a coluna e o componente a `pathname === "/dashboard"`.

### 5.2 Cabeçalho duplicado

`PageIntro` e o card “Período visível” competem pela hierarquia. Eles serão substituídos por um único card operacional com eyebrow, título, descrição, timezone/versão, tabs, navegação, refresh e CTA.

### 5.3 Células pequenas e horário truncado

A grade fixa em sete colunas divide o espaço remanescente e usa `truncate` no horário. A remoção do status rail já recupera largura, mas a grade também precisa de largura mínima por célula, altura maior, quebra controlada de intervalos e scroll horizontal contido em viewport estreita.

### 5.4 Detalhe permanente

O `DayPanel` ocupa mais uma coluna fixa. Ele será substituído por `Modal` HeroUI v3 aberto ao selecionar o dia, com estado, intervalos, fonte, prioridade, mensagem e botão de lápis. A edição reutilizará o `RuleWizard` e retornará o foco corretamente.

### 5.5 Regras legadas invisíveis

As ocorrências derivadas de `BusinessHoursConfig` não têm `source_rule_id` e não aparecem em “Regras publicadas”. `SpecialSchedule` também não é projetado pelo novo resolver quando já existe uma configuração semanal. A migration precisa converter a configuração semanal e exceções existentes em regras nativas identificáveis e editáveis.

### 5.6 Edição limitada

O wizard atual edita apenas o primeiro intervalo e não oferece uma ação direta por dia. Ele deve gerenciar uma lista de intervalos, permitir adicionar/remover blocos, trocar atendimento/ausência e validar sobreposição/ordem antes da mutation.

## 6. Decisões fechadas

- Branch: `feat/helpdesk-calendar-triage-integration`.
- Fonte de verdade: `HelpdeskSchedule` + `HelpdeskScheduleRule` + resolver estruturado.
- Compatibilidade: migration de dados para horários e exceções legadas; adapters continuam disponíveis durante rollout.
- UI: status rail apenas na dashboard; cabeçalho unificado; grade ampliada; detalhe em modal; edição rápida com lápis.
- Mensagem: Markdown limitado e provider-neutral, HTML seguro no `richText`, plain text sem marcadores, emojis preservados.
- Handoff: reavaliação do calendário no worker e antes do efeito, sem remover identidade, lifecycle ou idempotência do PR #105.
- Produção: nenhuma mutation, deploy ou teste com dados reais nesta request sem nova autorização explícita.

## 7. Riscos

- Migration incorreta pode alterar a semântica de `17:50`, Quinta Fire ou exceções existentes.
- Regras de ausência e serviço com mesma prioridade podem produzir escolha inesperada; a precedência deve ser testada.
- Merge incorreto pode regredir identidade do PR #105; testes focados nos fluxos Heimdall são gate obrigatório.
- `richText` pode ter capabilities diferentes por canal; o campo `text` deve ser suficiente isoladamente.
- O endpoint Conversations usado pelo legado não tem suporte oficial para envio em conta WhatsApp Business nativa; isso é um gate de staging, não uma garantia desta implementação.
- O worktree contém deleções antigas não relacionadas; não devem entrar em commit, stash ou artefato desta request.

## 8. Gate de saída do Research

Research concluída. O plano aprovado pelo pedido atual está em `01-plan/master-plan.md`. A implementação deve começar criando a branch a partir de `origin/main`, preservando todo drift não relacionado.
