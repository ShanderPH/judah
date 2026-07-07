> [Índice completo](../INDEX.md)

# Riscos de Segurança Conhecidos

## Riscos identificados no código

| Risco | Localização | Severidade | Notas |
|-------|-------------|------------|-------|
| `debug_mode=True` pode vazar prompts/secrets para logs | `apps/ai_agents/` | Alta | Verificar se `debug_mode` vem de env var |
| `except Ticket.DoesNotExist, ValueError:` (sintaxe Python 2) | `apps/support/services.py` | Média | **Corrigida**; auditar outros módulos |
| Webhooks HubSpot aceitos sem assinatura em DEBUG | `apps/webhooks/api.py`, `apps/ai_agents/api/webhooks.py` | Média | Apenas em desenvolvimento; comportamentos ligeiramente diferentes entre os dois routers |
| Endpoint de IA não montado | `apps/ai_agents/api/webhooks.py` | Média | Código existe mas não é exposto em `core/urls.py` |
| Variáveis `*_KEY` em texto plano no env | `.env` | Média | Usar cofre/antigravity secrets |
| Sem rate limiting nos endpoints de IA | `apps/ai_agents/api.py` | Média | Pode causar custos inesperados |
| Sem validação de permissão em alguns endpoints | `apps/health/api.py` | Baixa | Health checks são públicos por design |

## Riscos operacionais

- API keys da OpenAI podem ser expostas em logs de trace.
- `conftest.py` deleta tabelas de suporte; testes em DB errado causam perda de dados.
- Branch `production` protegida, mas deploy pode ocorrer sem smoke test manual.

## Arquivos relacionados

- [`security/recommendations.md`](./recommendations.md)
