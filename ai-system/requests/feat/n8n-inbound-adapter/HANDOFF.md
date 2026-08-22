# Handoff — JUDAH n8n inbound adapter

## Resumo do implementado

- Adaptou o endpoint HubSpot canônico para persistir e hidratar
  `conversation.newMessage` sem I/O com n8n na requisição.
- Implementou ledger canônico, transactional outbox, HMAC emissor, retry com
  jitter, dead-letter, recuperação de claims e polling durável.
- Serializou delivery ao n8n por `hubspot_thread_id` com lease PostgreSQL
  durável, recuperável e independente entre threads.
- Implementou reconciliação paginada de threads operacionais ativas usando o
  mesmo serviço atômico de ingestão do webhook.
- Adicionou prevenção de loops, métricas/logs sem PII, migration/RLS, testes e
  documentação de ativação/rollback.
- Não reintroduziu identificação, confirmação, triagem, menu, LLM, Matchmaker,
  prioridade, owner ou resposta do bot.

## Arquivos modificados ou criados

- `README.md`
- `core/settings/base.py`
- `core/settings/production.py`
- `apps/integrations/hubspot/client.py`
- `apps/integrations/tests/test_hubspot_conversations_client.py`
- `apps/webhooks/api.py`
- `apps/webhooks/metrics.py`
- `apps/webhooks/models.py`
- `apps/webhooks/n8n_inbound.py`
- `apps/webhooks/n8n_outbox.py`
- `apps/webhooks/reconciliation.py`
- `apps/webhooks/schemas.py`
- `apps/webhooks/tasks.py`
- `apps/webhooks/migrations/0007_webhookevent_delivery_method_and_more.py`
- `apps/webhooks/migrations/0008_n8nthreaddeliverylock.py`
- `apps/webhooks/tests/test_api_extended.py`
- `apps/webhooks/tests/test_hubspot_api.py`
- `apps/webhooks/tests/test_n8n_concurrency.py`
- `apps/webhooks/tests/test_n8n_inbound.py`
- `apps/webhooks/tests/test_n8n_outbox.py`
- `apps/webhooks/tests/test_reconciliation.py`
- `apps/webhooks/tests/test_schemas.py`
- `apps/webhooks/tests/test_tasks.py`
- `docs/ai/ai-context.md`
- `docs/architecture/n8n-inbound-adapter.md`
- `docs/architecture/overview.md`
- `docs/services/webhooks.md`
- `docs/setup/environment-variables.md`
- `ai-system/requests/feat/n8n-inbound-adapter/*`

## Como testar localmente

```powershell
.venv\Scripts\python.exe run_checks.py
.venv\Scripts\python.exe run_tests_local.py
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\mypy.exe apps core common
```

Última execução local: Django/migrations limpos; suíte completa com 742 testes
aprovados, 15 ignorados e 90,04% de cobertura; Ruff lint/formatação limpos; e
verificador n8n com 27/27 checks aprovados. Um smoke sintético controlado recebeu
HTTP 202 do webhook n8n e terminou em `DELIVERED`; ele não substitui um E2E
originado por uma mensagem real do HubSpot.

Para repetir a validação de concorrência real, configure somente um PostgreSQL
local descartável em `JUDAH_TEST_DATABASE_URL`; o runner recusa hosts remotos.
Nunca rode contra Supabase compartilhado. O gate local passou com 3/3 testes.

## Riscos conhecidos / áreas frágeis

- A contenção por thread passou em PostgreSQL local. RLS, permissões da role de
  runtime e a migration ainda precisam de verificação em staging antes de ativar.
- `mypy` 2.1.0 falha internamente ao inicializar `mypy-django` no Python 3.14,
  antes de analisar o projeto.
- A especificação não rastreada `docs/ai/n8n-inbound-integration-spec.md` descreve
  um boundary legado conflitante e foi preservada sem edição.
- `.env.example` não foi alterado porque `AGENTS.md` o declara área proibida;
  todos os nomes estão documentados no guia de variáveis.

## Pontos de integração críticos para VERIFY

1. Confirmar payload/aceitação real do WF-03 e comparação HMAC com os bytes exatos.
2. Confirmar scope HubSpot `conversations.read`, paginação e campos dos canais reais.
3. Repetir a contenção PostgreSQL em staging e validar RLS com a role de
   migration/runtime.
4. Provar recuperação após indisponibilidade de Redis e n8n.
5. Confirmar que nenhuma schedule Beat foi criada antes da autorização operacional.
6. Confirmar em staging que dois outboxes concorrentes para a mesma thread
   mantêm exatamente um lease ativo.
