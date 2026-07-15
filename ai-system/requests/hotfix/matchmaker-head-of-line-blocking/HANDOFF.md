# Handoff

## Resumo do implementado/corrigido

- Eliminado o bloqueio da fila pelo ticket obsoleto na cabeça: HTTP 404 agora coloca o item em quarentena auditável e o dreno continua.
- Adicionado backoff exponencial limitado e metadados de falha para erros recuperáveis do HubSpot.
- Unificado o processamento de pendências no matchmaker canônico, evitando dois fluxos de atribuição com comportamentos diferentes.
- Corrigida a reabertura do lifecycle para tickets que voltam ao estágio NOVO.
- Adicionada reativação segura de tickets em quarentena quando o HubSpot volta a publicá-los como válidos.

## Arquivos modificados

- `apps/integrations/hubspot/client.py`
- `apps/integrations/hubspot/exceptions.py`
- `apps/support/auto_assign_service.py`
- `apps/support/matchmaker_service.py`
- `apps/support/models.py`
- `apps/support/migrations/0014_newconversation_failure_tracking.py`
- `apps/support/api.py`
- `apps/support/queue_service.py`
- `apps/support/sat_service.py`
- `apps/support/tasks.py`
- `apps/ai_agents/services/lifecycle.py`
- `common/circuit_breaker.py`
- testes correspondentes em `apps/**/tests/` e `common/tests/`.

## Como testar localmente

```powershell
uv run ruff check .
uv run python run_checks.py
uv run python run_tests_local.py
```

Para o `mypy`, execute com as mesmas variáveis fictícias definidas em `run_tests_local.py`, em especial `DJANGO_ENV=test`, `DJANGO_SECRET_KEY` fictícia e `DATABASE_URL=sqlite:///:memory:`.

## Riscos conhecidos / áreas frágeis

- A migration `support.0014` precisa ser aplicada antes de iniciar o worker com o novo código.
- Erros globais de autenticação/configuração do HubSpot interrompem o dreno atual e são retomados com backoff; isso evita amplificar falhas do provedor.
- A quarentena preserva o registro para auditoria. Ele só volta à fila após um novo sinal válido do HubSpot.

## Pontos de integração críticos

- Aplicar a migration antes dos processos API/worker/beat.
- Após o deploy, confirmar no worker os eventos `matchmaker_ticket_quarantined` para o ticket obsoleto e `matchmaker_drain_done` com atribuições subsequentes.
- Verificar que o ticket `46735280255` deixa de aparecer repetidamente como cabeça ativa da fila.
