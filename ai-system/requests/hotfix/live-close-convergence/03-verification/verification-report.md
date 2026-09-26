# Verificação local e limites de produção

Base: `da124c841b30487d51a58b1ef289811795e0808a`. Branch: `hotfix/live-close-convergence`.

## RED/GREEN

- RED: observação de provider com estágio FECHADO e horário de fechamento ausente confirmava occupancy `closed` nos modos `shadow` e `enforce`, mantendo ciclo `assigned` e sem `ClosedConversation` (2 falhas reproduzidas).
- RED: exceção inesperada de `close_ticket_instances` era engolida e fechamento parecia aplicado (1 falha reproduzida).
- RED adicional: conflito de projeção preexistente confirmava occupancy `closed` enquanto ciclo permanecia `assigned` (1 falha reproduzida).
- GREEN: os quatro cenários passam; retry após falha de lifecycle converge; observação válida fecha ciclo e occupancy uma vez; rejeição preserva occupancy anterior; owner task em `shadow` faz retry da falha de fechamento.
- Teste de integração mostra `ConversationEvent.PROCESSED` com domínio ainda não aplicado quando o webhook apenas despachou a task.

## Gates finais

- `ruff format --check .`: 363 arquivos formatados.
- `ruff check .`: limpo.
- `mypy apps core common`: 360 arquivos, sem problemas, com `DJANGO_ENV=test` e banco SQLite local.
- `python run_tests_local.py`: 921 aprovados, 46 ignorados; cobertura 91,19%.
- Concorrência PostgreSQL local: 3 casos aprovados nos modos `off`, `shadow` e `enforce`, usando conexões independentes e `judah_test` descartável.
- `python manage.py makemigrations --check --dry-run`: `No changes detected`.
- `git diff --check`: limpo.

Uma execução intermediária da suíte falhou em teste não relacionado: a asserção procurava o texto `9001` numa lista de métricas e um valor de duração continha esses dígitos. Reexecução completa aprovou esse teste e todos os demais. Nenhuma alteração oportunista foi feita nesse teste.

## Produção: somente leitura

Consulta read-only de variáveis do `judah-worker` confirmou `DJANGO_ENV=production`, `RAILWAY_ENVIRONMENT_NAME=production`, `AVAILABILITY_AUTHORITY_ENVIRONMENT=production`, `SUPPORT_CAPACITY_MODE=enforce` e `CONVERSATION_CYCLES_ENFORCED=true`. Portanto, o worker consultado tem authority pelo predicado atual; falta de authority permanece um risco de configuração em outros runtimes, agora retryable.

Nenhuma query de escrita, task de reparo ou comando `--apply` foi executado em produção. A amostra limitada de logs não identificou as três ocorrências individualmente. O mecanismo é reproduzido pelo código e testes, mas a atribuição exata de cada ticket de produção exige correlação read-only por `source_event_id` após deploy.

## Consulta de validação após deploy

`live-close-cohorts.sql` abre transação `READ ONLY`, resolve ciclo por horário efetivo da ocorrência e separa `new_code` de `historical_backlog` pelo instante UTC real do deploy. O critério do P0 é `new_code = 0` durante janela operacional. A readiness expõe `recent_close_projection_inconsistencies` e a métrica agregada `ticket_close_projection_inconsistencies_recent` sem payload/PII.

P0 permanece aberto até a prova read-only do novo SHA em produção. O backlog anterior não impede a aprovação do caminho live e não foi reparado nesta etapa.
