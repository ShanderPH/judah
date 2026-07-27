# HANDOFF — ticket lifecycle routing

## Resumo do implementado/corrigido

- O handoff avisa o cliente antes do efeito externo e move o ticket para
  `HUBSPOT_SUPPORT_PIPELINE_ID / HUBSPOT_SUPPORT_NEW_STAGE_ID`.
- O Salomão não escreve `hubspot_owner_id`; owner humano e atribuição do
  Matchmaker são sempre preservados.
- Respostas conclusivas fecham o ticket em
  `HUBSPOT_AI_TRIAGE_PIPELINE_ID / HUBSPOT_CLOSED_STAGE_ID` somente depois da
  entrega da resposta ao cliente.
- Perguntas de esclarecimento permanecem abertas e uma nova mensagem recebida
  reabre a instância fechada da mesma conversa.
- Alterações no HubSpot são idempotentes, auditadas e falhas ficam retryable.
  Se a mensagem ao cliente já foi entregue, o retry retoma apenas o PATCH de
  rota/fechamento, sem repetir modelo ou mensagem.
- O Salomão só inicia e só publica respostas em
  `HUBSPOT_AI_TRIAGE_PIPELINE_ID / HUBSPOT_N1_NEW_STAGE_ID`. A rota é lida
  novamente imediatamente antes do envio; owner humano, participação humana,
  mudança de status ou novo turno suprimem a saída obsoleta sem retry.
- Rota/fechamento também fazem uma última hidratação imediatamente antes do
  PATCH. Supressão segura e mudança de turno são terminais.

## Arquivos modificados

- `apps/ai_agents/services/execution.py`
- `apps/ai_agents/services/hubspot.py`
- `apps/ai_agents/services/lifecycle.py`
- `apps/ai_agents/services/tool_permissions.py`
- `apps/ai_agents/api/webhooks.py`
- `apps/ai_agents/tasks.py`
- `apps/ai_agents/tests/test_hubspot_salomao_bridge.py`
- `apps/ai_agents/tests/test_lifecycle.py`
- `apps/ai_agents/tests/test_workflow_execution.py`
- `core/settings/base.py`
- `.github/workflows/ci.yml`
- `docker-compose.yml`
- `docs/business/workflows.md`
- `docs/services/ai_agents.md`
- `ai-system/requests/hotfix/ticket-lifecycle-routing/`

## Como testar localmente

```powershell
py -3.14 run_tests_local.py
ruff check .
ruff format --check .
py -3.14 -m mypy --no-incremental .
py -3.14 manage.py check --settings core.settings.test
py -3.14 manage.py makemigrations --check --dry-run --settings core.settings.test
```

O runner local força SQLite privado e credenciais placeholder. Para os
comandos Django e mypy, carregue as mesmas variáveis seguras definidas em
`run_tests_local.py`.

## Riscos conhecidos / áreas frágeis

- A API pública de Tickets do HubSpot não documenta compare-and-swap para
  PATCH. Por isso o Salomão não inclui owner no payload e revalida a rota
  imediatamente antes da mutação.
- O repositório público ainda não está habilitado no Codecov. O upload só roda
  quando `CODECOV_TOKEN` existir; a cobertura continua sendo gate obrigatório
  e independente por `pytest --cov-fail-under=90`.
- O smoke real depende do deploy simultâneo de web e worker e do webhook Judah
  canônico; o webhook separado do Salomão-Supremo permanece desativado.

## Pontos de integração críticos

- Confirmar após o deploy um pedido humano em `Support N1 / Novo`.
- Confirmar uma resposta conclusiva em `Triagem N1 / Fechado`.
- Confirmar que owners humanos não são substituídos e que uma nova mensagem
  recebida após fechamento inicia outro turno.
- Confirmar que uma task iniciada antes de um atendimento humano não publica
  resposta tardia nem altera o ticket depois da tomada humana.
