# HANDOFF — lifecycle terminal reopen

## Resumo do implementado/corrigido

- Corrigida a transição legítima `QUEUE_PENDING -> CONTEXT_HYDRATING`.
- Uma thread fechada agora pode voltar ao processamento somente após a rota de
  IA atual ser validada no HubSpot.
- O guardrail de resposta tardia permanece ativo: pipeline, etapa, owner,
  participação humana e turno atual são revalidados antes da publicação.
- Turnos já respondidos são deduplicados independentemente do estado atual da
  instância.
- Erros em instâncias terminais não são mais mascarados por uma segunda
  transição inválida; colisões de idempotência usam savepoint transacional.
- A reidratação final não perde mais o ticket quando o HubSpot omite a
  associação da thread; uma associação atual divergente continua prevalecendo.
- Logs agora distinguem no-op seguro, retry agendado e exaustão, com
  identificadores, motivo e próxima ação.
- O worker Celery preserva o pipeline JSON do Django/structlog, evitando INFO
  em formato texto no `stderr` classificado como erro pelo Railway.

## Arquivos modificados

- `apps/ai_agents/api/webhooks.py`
- `apps/ai_agents/agents/base.py`
- `apps/ai_agents/agents/supervisor.py`
- `apps/ai_agents/services/hubspot.py`
- `apps/ai_agents/services/lifecycle.py`
- `apps/ai_agents/tasks.py`
- `apps/ai_agents/tests/test_ai_webhooks_extended.py`
- `apps/ai_agents/tests/test_hubspot_salomao_bridge.py`
- `apps/ai_agents/tests/test_lifecycle.py`
- `apps/ai_agents/tests/test_tasks.py`
- `apps/support/tasks.py`
- `apps/support/tests/test_tasks_extended.py`
- `apps/webhooks/handlers/hubspot_handler.py`
- `apps/webhooks/services.py`
- `apps/webhooks/tests/test_services.py`
- `core/settings/base.py`
- `core/tests/test_settings_environments.py`
- `ai-system/requests/hotfix/lifecycle-terminal-reopen/`

## Como testar localmente

```powershell
py -3.14 run_tests_local.py
py -3.14 -m ruff check .
py -3.14 -m ruff format --check .
py -3.14 -m mypy --no-incremental .
py -3.14 manage.py check --settings core.settings.test
py -3.14 manage.py makemigrations --check --dry-run --settings core.settings.test
```

Para mypy e comandos Django, use as variáveis placeholder do
`run_tests_local.py`; não carregue `.env` de staging ou produção.

## Riscos conhecidos / áreas frágeis

- O hotfix ainda não foi implantado; os ambientes remotos continuam com o
  comportamento anterior até merge e deploy.
- O smoke real depende de uma nova mensagem numa conversa em
  `HUBSPOT_AI_TRIAGE_PIPELINE_ID / HUBSPOT_N1_NEW_STAGE_ID`.
- Redelivery do mesmo turno e tomada humana concorrente devem permanecer
  suprimidos; ambos estão cobertos por testes automatizados.

## Pontos de integração críticos

- Confirmar resposta a uma nova mensagem em thread anteriormente fechada.
- Confirmar ausência de resposta ao mover um ticket sem uma nova mensagem.
- Confirmar ausência de resposta depois de owner ou agente humano assumir.
- Confirmar que o log de uma falha mostra a exceção original sem erro
  secundário de transição terminal.
- Confirmar no Railway que eventos INFO do Celery aparecem como JSON/INFO e
  que somente a exaustão de retries aparece como ERROR.
