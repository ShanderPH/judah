# Master Plan — Helpdesk Calendar integrado à triagem nativa

## 1. Objetivo

Concluir o calendário operacional do Helpdesk, corrigir sua UX, tornar as regras antigas e novas gerenciáveis e integrar sua resolução com a triagem Heimdall do PR #105 sem regredir identidade, lifecycle, segurança, idempotência ou Matchmaker.

## 2. Escopo

Incluído:

- alinhar a branch ao `origin/main` que contém o PR #105;
- portar e consolidar a implementação local do calendário;
- migrar horários e exceções legadas para regras editáveis;
- tornar o novo resolver a autoridade compartilhada por UI, dispatcher, worker e handoff;
- melhorar `/calendar` conforme os itens 1.1–1.5;
- validar e testar ausência/mensagem para WhatsApp e webchat conforme o contrato HubSpot;
- atualizar testes, documentação, STATUS, HANDOFF e resumo final.

Fora do escopo sem nova autorização:

- deploy, push, abertura/merge de PR;
- migrations ou testes em banco não-local;
- envio de mensagem real ou mutation em ticket HubSpot de produção;
- remoção definitiva dos modelos/endpoints legados.

## 3. Arquitetura alvo

```text
HubSpot webhook
  -> lifecycle/identity/Heimdall do PR #105
  -> task Celery reavalia HelpdeskScheduleResolver
  -> ConversationContext recebe ScheduleResolution tipado
  -> Supervisor decide resposta ou handoff
  -> antes do handoff, resolução é revalidada
  -> send_reply_with_audit envia text + richText idempotentes
  -> pipeline/estágio/Matchmaker seguem a decisão atual

WebApp /calendar
  -> BFF autenticado e allowlisted
  -> API Ninja tipada
  -> HelpdeskSchedule / Rule / Interval / AbsenceMessage
```

## 4. Contratos e invariantes

- Intervalos seguem `[start, end)` no timezone IANA do calendário.
- Ausência vence atendimento no mesmo instante; dentro do mesmo tipo vence maior prioridade e depois ID estável.
- Nenhum caminho de runtime decide horário a partir de cache do browser.
- O worker reavalia o calendário no instante da execução.
- A mensagem armazenada não aceita HTML bruto como autoridade.
- `text` é plain text obrigatório; `richText` é HTML escapado derivado.
- Para WhatsApp Business nativo, tratar o transporte como risco explícito: a documentação oficial não suporta envio por Conversations API, portanto exigir prova em staging ou adaptador alternativo antes do rollout.
- Emojis e quebras de linha são preservados.
- Toda mutation administrativa exige capability, auditoria, idempotency key e optimistic concurrency.
- Nenhum arquivo do PR #105 pode perder `CustomerIdentity`, confidence gates ou lifecycle de coleta.

## 5. Work packages

### OPS-01 — Branch e preservação do worktree

1. Criar `feat/helpdesk-calendar-triage-integration` a partir de `origin/main`.
2. Transportar apenas os paths da implementação do calendário.
3. Resolver sobreposições preservando integralmente o PR #105.
4. Manter deleções e arquivos alheios fora de staging/commit.

Aceite:

- `git merge-base HEAD origin/main` contém `488eeecf`;
- `git status` distingue mudanças da request e drift preexistente;
- nenhum arquivo de outra request é restaurado ou removido.

### DB-01 — Migração do domínio e dados legados

1. Revisar a migration `0028` para PostgreSQL 16 e SQLite local.
2. Adicionar `RunPython` idempotente que converte:
   - `BusinessHoursConfig` ativo em regras semanais editáveis;
   - `SpecialSchedule.closed` em ausência de alta prioridade;
   - `SpecialSchedule.custom` em atendimento pontual de alta prioridade.
3. Preservar a normalização histórica de segunda a sexta `09:00–17:50` quando a configuração antiga contém `9–18`.
4. Representar Quinta Fire sem perder o restante da quinta-feira.
5. Manter reverse migration segura; as tabelas novas são removidas no rollback do schema.

Aceite:

- dados existentes aparecem em `rules` com IDs editáveis;
- exceção vence regra semanal;
- migration é determinística, repetível em teste e sem DROP/TRUNCATE explícito;
- `makemigrations --check --dry-run` não gera drift.

### BE-01 — Resolver e contrato tipado

1. Consolidar `HelpdeskScheduleResolver`/funções atuais em um serviço determinístico.
2. Introduzir `ScheduleResolution` tipado no contrato de conversação.
3. Corrigir serialização de intervalos por weekday/data e múltiplos blocos.
4. Validar sobreposição, recorrência, vigência e tamanho/formato da mensagem.
5. Manter fallback legado apenas para rollout/migration indisponível, com log estruturado.

Aceite:

- resolver retorna estado, `is_open_now`, intervalos, motivo, mensagem, fonte e prioridade;
- limites, recorrências, ausência e múltiplos intervalos têm testes;
- nenhuma chamada ORM síncrona ocorre dentro de async sem `sync_to_async`.

### BE-02 — API administrativa e gerenciamento

1. Manter endpoints list/create/update/deactivate/preview/resolve tipados.
2. Garantir que GET principal sempre retorne regras editáveis, inclusive migradas.
3. Preservar `support.admin.read` para leitura e `support.calendar.manage` para mutations.
4. Corrigir erro/conflito de edição com `expected_version` e retorno 409.
5. Preservar auditoria e idempotência.

Aceite:

- regra existente pode ser aberta, alterada e salva;
- múltiplos intervalos fazem round-trip;
- viewer/agent não gerenciam; manager/admin autorizados são auditados.

### INT-01 — Integração com PR #105

1. Fazer `agent_sync_service.is_business_hours()` delegar ao novo resolver.
2. Reavaliar `ScheduleResolution` nas tasks de ticket e thread.
3. Unir `ScheduleResolution` e `CustomerIdentity` em `ConversationContext`.
4. Preservar os gates de identidade/confiança e a espera auditada do PR #105.
5. Antes do handoff, usar a resolução atual para pipeline/estágio e confirmação.
6. Manter idempotency keys independentes da origem do webhook.

Aceite:

- triagem, handoff e UI concordam para o mesmo instante;
- mudança entre dispatch e execução é observada pelo worker;
- ausência fornece a mensagem configurada;
- todos os testes novos do PR #105 continuam verdes.

### INT-02 — Mensagens HubSpot, WhatsApp e webchat

1. Formalizar Markdown limitado aceito no editor: parágrafos, quebras, `**negrito**` e emojis.
2. Gerar plain text removendo marcadores e HTML seguro escapado para `richText`.
3. Enviar ambos os campos no endpoint HubSpot já usado pelo runtime.
4. Manter fallback apenas `text` semanticamente correto quando rich text não for suportado.
5. Testar raw HTML, bold, emoji, multiline e idempotência.

Aceite:

- nenhum HTML do administrador chega sem escaping;
- o texto plano é legível sem sintaxe residual;
- emoji permanece idêntico;
- ausência não duplica reply em replay/retry.

### FE-01 — App shell por rota

1. Usar `usePathname()` no client `AppShell`.
2. Renderizar `StatusRail` e a terceira coluna somente em `/dashboard`.
3. Expandir o conteúdo das outras rotas até o limite disponível.

Aceite:

- dashboard mantém o rail;
- `/calendar`, `/queue`, `/agents`, `/metrics` e `/auto-assignment` não reservam a coluna;
- navegação client-side atualiza o layout sem reload completo.

### FE-02 — Cabeçalho e grade do calendário

1. Unificar PageIntro, período, timezone, versão, tabs e ações em um Card HeroUI.
2. Aumentar largura/altura mínima das células.
3. Mostrar cada intervalo completo, sem `truncate` destrutivo.
4. Adicionar scroll horizontal contido em telas estreitas e leitura em mobile.
5. Preservar grid semantics, focus ring e `aria-selected`.

Aceite:

- horários como `09:00–12:00, 13:00–17:50` ficam visíveis;
- mês e semana funcionam com teclado;
- nenhum conteúdo fica sob o status rail.

### FE-03 — Modal do dia e edição rápida

1. Remover o painel lateral permanente.
2. Abrir `Modal` HeroUI ao selecionar dia.
3. Exibir estado, intervalos, regra vencedora, prioridade e mensagem.
4. Adicionar botão icon-only com lápis e label acessível.
5. Encadear o modal do dia ao wizard de edição da regra fonte.
6. Para dia sem regra específica, oferecer criação com data pré-preenchida.

Aceite:

- foco entra e retorna corretamente;
- lápis edita a regra correta por ID;
- modal fecha por ação, Escape e backdrop conforme HeroUI;
- mobile não possui painel fixo estreitando a grade.

### FE-04 — Wizard e lista de regras

1. Tornar intervalos um array editável.
2. Permitir adicionar/remover intervalos e alterar atendimento/ausência.
3. Validar ordem e sobreposição antes do POST/PATCH.
4. Exibir lista mesmo vazia, com estado e CTA.
5. Mostrar mensagens de erro e conflito sem perder o formulário.
6. Documentar bold/emojis no editor de ausência.

Aceite:

- regra legada migrada é editável;
- múltiplos intervalos são preservados;
- ausência não exige horários e atendimento exige ao menos um;
- double submit é bloqueado.

### V-01 — Verificação backend

- migration forward/reverse em banco local descartável;
- testes do resolver, API, RBAC, auditoria e concorrência;
- testes PR #105 focados em identidade, supervisor, tasks, webhook e handoff;
- `ruff`, `mypy`, `django check`, `makemigrations --check`;
- suite local segura via `run_tests_local.py` quando viável.

### V-02 — Verificação frontend

- testes Vitest de período, intervalos e transformação de estado;
- lint, typecheck, testes e build;
- navegador autenticado local para dashboard e `/calendar`;
- viewport desktop/mobile, modal, edição, teclado, tema e reduced motion;
- screenshot em `03-verification/` quando o browser permitir.

### OPS-02 — Preparação de rollout

1. Documentar ordem: migration → deploy desabilitado/shadow → smoke staging → rollout pequeno.
2. Stop gates:
   - divergência calendário/UI/runtime;
   - reply duplicada;
   - handoff aberto durante ausência;
   - perda de identity/confidence gate;
   - erro de migration ou regra legada ausente.
3. Rollback de código volta adapters ao legado; tabelas permanecem até confirmação.

## 6. Sequência de implementação

1. OPS-01.
2. DB-01 + BE-01.
3. Merge técnico do PR #105 + INT-01.
4. BE-02 + INT-02.
5. FE-01.
6. FE-02 + FE-03 + FE-04.
7. V-01 + V-02.
8. OPS-02, HANDOFF, STATUS e resumo de apresentação.

## 7. Critérios de aceitação consolidados

- Status rail somente na dashboard.
- `/calendar` usa toda a largura disponível.
- Um único card apresenta contexto e controles do período.
- Células mostram horários completos e múltiplos intervalos.
- Clique em dia abre modal; lápis edita a regra fonte.
- Horários/exceções pré-calendário aparecem e podem ser alterados.
- Ausência vence atendimento e sua mensagem chega ao handoff atual.
- Webchat/custom channel recebe `text` legível e `richText` seguro; WhatsApp nativo só pode ser aprovado após validar um transporte suportado em staging.
- Triagem do PR #105 preserva identidade, confidence gates, lifecycle e idempotência.
- Lint, tipos, testes, build e smoke local ficam verdes ou têm limitação documentada.

## 8. Gate de autorização

O pedido de 2026-08-15 autoriza expressamente Research, Planning e Implementing, incluindo criação de branch, codificação, testes e preparação para deploy. Ele não autoriza push, PR, deploy, migration remota, mutation HubSpot ou teste conectado a base não-local.
