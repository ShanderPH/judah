# Handoff

## Resumo do implementado

- Alinhado o webhook canônico, roteamento determinístico e lifecycle ao fluxo
  executivo anexado.
- Adicionados contratos estruturados, espera pelo cliente e confirmação antes
  do fechamento por IA.
- Centralizados efeitos externos com permissão por estado, idempotência,
  `AgentRun` e `ToolCallAuditLog`.
- Integrados handoff via Matchmaker, retries limitados, watchdog e fallback
  seguro.
- Reforçadas assinatura HubSpot v3, sanitização de conteúdo e minimização de
  PII em auditoria.

## Arquivos modificados

- `apps/ai_agents/`
- `apps/webhooks/`
- `apps/support/matchmaker_service.py`
- `common/logging.py`
- `core/settings/base.py`
- `README.md`
- `docs/`

## Como testar localmente

```powershell
ruff check .
ruff format --check .
python -m mypy .
python run_checks.py
python run_tests_local.py
```

## Riscos conhecidos / áreas frágeis

- A detecção de prompt injection é determinística e deve ser acompanhada por
  evals e métricas de falsos positivos.
- O worker síncrono do Celery ainda usa `asyncio.run` para o pipeline async.
- O rollout real depende da configuração consistente de API, worker, beat,
  Redis, HubSpot e feature flags.

## Pontos de integração críticos

- Aplicar as migrations `ai_agents.0004` e `webhooks.0005`.
- Confirmar que Celery Beat executa watchdog e retry dispatcher.
- Validar em sandbox HubSpot os canais, permissões de resposta e transições do
  Matchmaker.
