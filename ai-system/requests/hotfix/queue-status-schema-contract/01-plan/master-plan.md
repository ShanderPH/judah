# Master Plan — Hotfix do contrato `queue_status`

## 1. Objetivo

Restabelecer a convergência segura da fila de autoatribuição em produção,
eliminando o conflito entre o estado `failed` usado pela aplicação e a CHECK
constraint do Supabase, além de tornar o caminho concorrente de criação de
`ConversationInstance` transacionalmente correto.

Este plano será executado somente após uma nova solicitação explícita do
Felipe. A criação deste artefato não autoriza implementação, migration em
produção, deploy, limpeza/replay da fila ou merge em `main`.

## 2. Escopo

### Incluído

- Migration explícita, idempotente e reversível para o contrato de
  `new_conversations.queue_status`.
- Teste de contrato que reproduza a constraint real do Supabase.
- Correção do tratamento concorrente de `ConversationInstance` com savepoint
  seguro ou operação ORM equivalente.
- Testes de regressão para o drain, quarentena e corrida de idempotência.
- Atualização da documentação do modelo e runbook de rollback.
- Validação read-only do estado produtivo antes e depois do deploy.

### Excluído

- Habilitar `CONVERSATION_CYCLES_ENFORCED`.
- Backfill/reconciliação global de ciclos legados.
- Apagar linhas de `new_conversations`.
- Reexecutar, atribuir ou alterar owner de tickets sem prova no HubSpot.
- Refactor arquitetural do Matchmaker ou do lifecycle.
- Correções dos lints gerais de performance do Supabase.

## 3. Critérios de aceitação

1. A constraint real aceita exatamente `pending`, `queued` e `failed` e
   continua rejeitando qualquer outro valor.
2. A migration é segura se executada novamente e possui rollback documentado.
3. Uma linha legada ambígua transiciona para `failed` sem efeito no HubSpot.
4. A falha/quarentena de uma linha não impede o drain de processar as demais.
5. Linhas já atribuídas ou manualmente tratadas não são reproduzidas.
6. O Beat deixa de gerar violações de
   `new_conversations_queue_status_check`.
7. O caminho concorrente de lifecycle não consulta dentro de uma transação
   marcada para rollback.
8. Duas gravações concorrentes da mesma identidade convergem para uma única
   `ConversationInstance` e preservam os eventos idempotentes.
9. Documentação, models, migrations e schema verificado descrevem o mesmo
   domínio.
10. O rollback não remove histórico nem reabre efeitos externos.

## 4. Plano de execução por Gate

### Gate A — Revalidar produção, somente leitura

Tasks:

- `OPS-01`: confirmar projeto, branch base, SHA e deployments atuais.
- `DB-01`: reconsultar a definição de
  `new_conversations_queue_status_check`.
- `DB-02`: capturar somente agregados de fila, ciclos, tentativas e projeções.
- `OPS-02`: correlacionar logs do Beat/worker com a recorrência PostgreSQL.
- `OPS-03`: confirmar que `CONVERSATION_CYCLES_ENFORCED` permanece `false`.

Saída esperada: snapshot pré-hotfix sem PII em `03-verification/`.

Parada obrigatória: qualquer divergência material do diagnóstico exige revisão
do plano antes de escrever código.

### Gate B — Contrato de schema

Tasks:

- `DB-03`: criar migration Django/Supabase explícita que substitua a CHECK por
  `queue_status IN ('pending', 'queued', 'failed')`.
- `DB-04`: tornar a operação idempotente por inspeção do catálogo, sem depender
  apenas de o nome da migration estar marcado como aplicado.
- `DB-05`: documentar down migration que restaure a constraint anterior apenas
  após provar que não existem linhas `failed`; caso existam, o rollback deve
  falhar fechado e orientar restauração do código/schema compatível.
- `DB-06`: adicionar comentário SQL documentando a autoridade do contrato.

Decisão de implementação preferida:

1. validar previamente os valores distintos existentes;
2. remover somente a constraint conhecida;
3. recriá-la com os três valores permitidos;
4. validar a definição resultante via `pg_get_constraintdef`.

Não usar alteração de `choices` como substituto para DDL explícito.

### Gate C — Resiliência da fila

Tasks:

- `BE-01`: preservar os caminhos atuais de quarentena `stale_cycle`,
  `legacy_cycle_ambiguous` e erro permanente.
- `BE-02`: garantir que uma falha inesperada de persistência produza resultado
  sistêmico observável e não métricas de progresso falsas.
- `BE-03`: garantir isolamento por item/savepoint no drain caso a migration
  revele outro erro de dados.
- `BE-04`: não alterar owner HubSpot nem criar nova `AssignmentAttempt` ao
  convergir linha ambígua.

O menor patch que satisfaça os critérios deve ser preferido. Se `BE-02/03`
exigir refactor em mais de cinco arquivos, promover o Ciclo M para Ciclo F e
solicitar nova aprovação.

### Gate D — Concorrência do lifecycle

Tasks:

- `BE-05`: encapsular o INSERT concorrente em `transaction.atomic()` interno
  para criar savepoint, capturando `IntegrityError` somente após o rollback do
  savepoint; ou adotar primitiva ORM equivalente comprovadamente segura.
- `BE-06`: recuperar a instância vencedora pela chave idempotente após a
  colisão.
- `BE-07`: preservar uma única instância, eventos distintos e nenhuma
  duplicação de efeito por turn/event key.
- `BE-08`: manter o fallback determinístico como defesa, não como caminho
  normal de concorrência.

### Gate E — Testes e contrato produtivo

Tasks:

- `V-01`: teste PostgreSQL 16 para `pending`, `queued`, `failed` e valor
  inválido.
- `V-02`: teste de migration forward e backward em banco descartável.
- `V-03`: teste de linha legacy/cycle-null com tentativa completed: quarentena
  sem nova atribuição.
- `V-04`: teste de stale cycle e permanent provider failure.
- `V-05`: teste de drain com um item quarentenável seguido por item válido,
  provando progresso e ausência de head-of-line blocking.
- `V-06`: teste concorrente de lifecycle com duas transações/processos reais
  em PostgreSQL; SQLite não é prova suficiente.
- `V-07`: regressões focadas de webhook/lifecycle e durable assignment.
- `V-08`: suíte repo-native via `run_tests_local.py`, Ruff, format, mypy,
  `manage.py check`, `makemigrations --check --dry-run` e `git diff --check`.
- `V-09`: comparar o SQL gerado/aplicado com `pg_get_constraintdef` esperado.

Guardrail: nenhum teste pode apontar para base não local. O isolamento do
`conftest.py` torna essa validação destrutiva fora de banco descartável.

### Gate F — Documentação e handoff

Tasks:

- `DOC-01`: atualizar `docs/database/models.md` para incluir `failed` e seu
  significado de quarentena.
- `DOC-02`: registrar autoridade e ordem entre migrations Supabase e Django.
- `OPS-04`: criar runbook de deploy, observação e rollback em
  `05-deployment/`.
- `OPS-05`: preencher `HANDOFF.md` com arquivos, comandos, riscos e primeira
  matriz de ataque do VERIFY.

### Gate G — PR e merge direto em `main`

Tasks:

- `OPS-06`: revisar o diff para excluir drift preexistente (`.hs/`, `uv.lock`,
  `docs/evidences/` e outros arquivos fora da request).
- `OPS-07`: commit Conventional Commit em inglês e push da branch.
- `OPS-08`: abrir PR `hotfix/queue-status-schema-contract -> main` com plano de
  rollback e evidência PostgreSQL.
- `V-10`: inspecionar logs brutos dos checks, não apenas o estado verde.
- `OPS-09`: merge direto em `main` somente após autorização explícita para o
  Gate G e checks obrigatórios aprovados.

Branch protegida: nenhum commit direto em `main`.

### Gate H — Deploy e convergência controlada

Tasks:

- `OPS-10`: confirmar Railway auth, projeto, ambiente, serviços e SHA.
- `DB-07`: aplicar a migration pelo caminho de deploy autorizado.
- `V-11`: provar a constraint real pelo catálogo após migration.
- `V-12`: observar API, worker, Beat e logs PostgreSQL durante pelo menos dois
  ciclos de drain.
- `V-13`: confirmar que a violação de CHECK cessou e que a fila ativa diminui
  por quarentena/convergência, sem nova atribuição externa indevida.
- `V-14`: verificar owner HubSpot dos casos sem projeção aberta antes de
  qualquer replay ou recuperação manual.
- `V-15`: confirmar que lifecycle UNIQUE conflicts não resultam em transação
  quebrada, evento perdido ou efeito duplicado.

Deploy e qualquer recuperação/replay são autorizações separadas. A migration
não autoriza reatribuição de tickets.

## 5. Rollback

### Código

- Reverter o commit do hotfix por PR.
- Manter a constraint ampliada durante rollback de código é compatível com a
  versão anterior, pois `pending` e `queued` continuam aceitos.

### Schema

- Não reduzir imediatamente a CHECK para dois valores se existirem linhas
  `failed`.
- Primeiro provar contagem e destino das linhas `failed`.
- Qualquer transformação/reabertura dessas linhas requer plano e autorização
  próprios; nunca convertê-las silenciosamente para `pending`/`queued`.

### Operação

- Se o drain produzir efeitos externos inesperados, suspender apenas o writer
  autorizado/serviço afetado conforme runbook; preservar tentativas e logs.
- Não limpar a fila como rollback automático.

## 6. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Migration marcada como aplicada mas constraint ainda antiga | Verificar catálogo antes e depois; DDL explícito e idempotente |
| Quarentena de linha já atribuída | Quarentena não altera HubSpot; conferir owner antes de replay |
| Head-of-line persiste por outro erro | Isolamento por item e telemetria de resultado sistêmico |
| Teste local diverge do Supabase | Lane PostgreSQL com a migration SQL real |
| Rollback rejeita linhas `failed` | Manter schema expandido ou falhar fechado até reconciliação |
| Corrida do lifecycle duplica fallback | Savepoint interno e teste concorrente real |
| Drift não relacionado entra no PR | Staging seletivo e inspeção do diff/commit |

## 7. Evidências mínimas para declarar concluído

- Constraint produtiva exibida pelo catálogo com três valores.
- Zero nova violação de `new_conversations_queue_status_check` na janela
  observada pós-deploy.
- Contagens antes/depois de queue rows, tentativas e ciclos, sem PII.
- Nenhuma nova `AssignmentAttempt`/mudança HubSpot causada pela quarentena.
- Teste concorrente do lifecycle aprovado em PostgreSQL.
- Checks completos e logs brutos anexados à request.
- `HANDOFF.md`, runbook e `STATUS.md` atualizados.

## 8. Próxima autorização esperada

Quando solicitado, iniciar pelo **Gate A — Revalidar produção, somente
leitura**. Nenhum Gate posterior é implicitamente autorizado pela aprovação do
Gate A.
