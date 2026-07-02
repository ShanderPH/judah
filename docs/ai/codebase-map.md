> [Índice completo](../INDEX.md)

# Mapa do Código

## Estrutura de diretórios

```text
judah/
├── apps/
│   ├── auth_user/       # autenticação e usuários
│   ├── church/          # igrejas, planos, gateways
│   ├── knowledge/       # base de conhecimento
│   ├── support/         # atendimento e fila
│   ├── ai_agents/       # agentes de IA
│   ├── webhooks/        # webhooks HubSpot/Jira
│   ├── analytics/       # métricas e relatórios
│   ├── integrations/    # integrações externas
│   ├── health/          # health checks
│   └── webapp/          # views legadas/admin
├── common/              # utilitários, permissões, errors
├── config/              # configurações do projeto
├── core/                # settings, urls, wsgi, asgi
├── docs/                # documentação
├── requirements/        # dependências
├── manage.py
├── celery_app.py
└── Dockerfile
```

## Arquivos-chave

| Arquivo | Propósito |
|---------|-----------|
| `core/settings/base.py` | Configurações base |
| `core/settings/production.py` | Overrides de produção |
| `core/urls.py` | Registro de rotas |
| `celery_app.py` | Configuração do Celery |
| `apps/support/services.py` | Lógica principal da fila |
| `apps/ai_agents/agents/salomao.py` | Agente Salomão |
| `apps/ai_agents/agents/heimdall.py` | Supervisor Heimdall |
| `apps/webhooks/services.py` | Processamento de webhooks |
| `common/permissions.py` | RBAC |
| `common/errors.py` | Exceções padronizadas |

## Convenções

- Cada app tem `models.py`, `api.py`, `services.py`, `tasks.py` (quando aplicável).
- `selectors.py` centraliza consultas complexas.
- `schemas.py` define contratos de API.
- Testes ficam em `apps/<app>/tests/`.

## Arquivos relacionados

- [`ai/module-index.md`](./module-index.md)
