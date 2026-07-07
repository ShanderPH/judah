> [Índice completo](../INDEX.md)

# Notas de Manutenção

## Problemas conhecidos

1. **Sintaxe Python 2 em `support/services.py`**
   - `except Ticket.DoesNotExist, ValueError:` foi corrigido para `except (Ticket.DoesNotExist, ValueError):`.
   - Verificar `auto_assign_service.py` e `hubspot_handler.py` por vestígios restantes.

2. **Campo inexistente em `analytics/services.py`**
   - `compute_daily_report` referencia `Ticket.Status.RESOLVED`, `Ticket.resolved_at` e `Ticket.sla_breached`, mas esses campos não existem no modelo.

3. **Circuit breaker não janela deslizante**
   - Implementação atual conta falhas desde o início do processo.
   - Recomenda-se refatorar para janela deslizante.

4. **`debug_mode` de agentes de IA**
   - Verificar se vem de variável de ambiente e se está `False` em produção.

## Tarefas técnicas recomendadas

| Prioridade | Tarefa | Motivo |
|------------|--------|--------|
| Alta | Corrigir sintaxe `except` | Impede deploy |
| Alta | Adicionar testes para fila de atribuição | Garantir estabilidade |
| Média | Refatorar circuit breaker | Confiabilidade |
| Média | Adicionar rate limiting em endpoints de IA | Controle de custo |
| Média | Revisar logs para não vazar secrets | Segurança |
| Baixa | Documentar campos JSON de modelos | Manutenibilidade |

## Dicas para debugging

- Use `structlog` com `request_id` para rastrear requisições.
- Verifique filas do Celery com `celery -A core.celery inspect active`.
- Health checks estão em `/api/v1/health/` (liveness) e `/api/v1/health/ready` (readiness).
- Para problemas de IA, verifique `AgentTrace` e `TokenTrackingLog`.

## Arquivos relacionados

- [`security/risks.md`](../security/risks.md)
- [`contributing/testing-guide.md`](../contributing/testing-guide.md)
