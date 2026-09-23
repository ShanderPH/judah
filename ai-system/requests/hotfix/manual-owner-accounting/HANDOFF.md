# HANDOFF — contabilização de owner manual

## Resumo do implementado/corrigido

- Remove `sourceId` da resolução do owner anterior do webhook.
- Usa o owner confirmado pela reconciliação no modo de capacidade `shadow`.
- Usa a `AssignedConversation` bloqueada como origem contábil da transferência.
- Serializa mudanças por ticket e preserva a rejeição de eventos atrasados com `previousValue` real.
- Adiciona regressões para payload sem anterior e com `sourceId` numérico enganoso.

## Arquivos modificados

- `apps/support/tasks.py`
- `apps/support/tests/test_manual_assignment_capacity.py`
- `apps/support/tests/test_ticket_lifecycle.py`
- `ai-system/requests/hotfix/manual-owner-accounting/`

Os arquivos preexistentes `docker-compose.yml` e `webapp/package*.json` não pertencem ao hotfix e devem
continuar fora do commit.

## Como testar localmente

```bash
DJANGO_ENV=test DATABASE_URL=sqlite:///./.test.sqlite3 DJANGO_SECRET_KEY=test-only \
  .venv/bin/python -m pytest apps/support/tests/ -q
.venv/bin/python -m ruff format --check apps/support/tasks.py \
  apps/support/tests/test_manual_assignment_capacity.py apps/support/tests/test_ticket_lifecycle.py
.venv/bin/python -m ruff check apps/support/tasks.py \
  apps/support/tests/test_manual_assignment_capacity.py apps/support/tests/test_ticket_lifecycle.py --no-cache
.venv/bin/python -m mypy apps/support/tasks.py
```

## Smoke pós-deploy e ativação

1. Manter `OPENING_COHORT_BARRIER_MODE=shadow` no deploy inicial.
2. Confirmar API, worker e Beat no mesmo SHA.
3. Fazer uma transferência manual controlada A→B e confirmar uma única atualização da projeção, dos
   contadores e de `ConversationReassignment`.
4. Confirmar ausência de retries contínuos em `task_handle_owner_change` e ausência de novas coortes
   órfãs após fila vazia.
5. Depois da confirmação explícita do usuário, configurar `OPENING_COHORT_BARRIER_MODE=enforce` nos
   serviços que consomem a flag e redeployar.
6. Na abertura seguinte, confirmar que backlog anterior à abertura fica adiado enquanto houver membro
   inicial `stabilizing`, e que libera por `all_settled` ou deadline.

## Riscos conhecidos / áreas frágeis

- O smoke depende de uma transferência real controlada; a suíte local simula a fronteira HubSpot.
- A barreira `enforce` pode aumentar temporariamente o tempo de espera do backlog até estabilização ou
  deadline; esse é o comportamento pretendido para evitar concentração na abertura.
- Este rollout é de `OPENING_COHORT_BARRIER_MODE`. `SUPPORT_CAPACITY_MODE=enforce` permanece fora do
  escopo e não deve ser ativado junto.

## Pontos de integração críticos

- Owner confirmado pelo HubSpot, projeção local bloqueada e contador devem convergir para o mesmo ticket.
- API, worker e Beat precisam compartilhar código e flags antes da ativação da barreira.
- Rollback operacional: retornar somente a barreira para `shadow` e redeployar.
