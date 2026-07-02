# Autenticação e Autorização

## Resumo

A API do JUDAH usa JWT (JSON Web Tokens) com algoritmo HS256 para autenticação. A autorização é baseada em papéis (`role`) do modelo `User`.

## Contexto

A autenticação é fornecida pelo pacote `django-ninja-jwt`. Tokens são emitidos no login, rotacionados no refresh e invalidados via blacklist no logout.

## JWT

### Configuração

```python
NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": config("DJANGO_SECRET_KEY"),
    "AUTH_HEADER_TYPES": ("Bearer",),
}
```

### Header de autenticação

```http
Authorization: Bearer <access_token>
```

### Tokens

- **Access token:** válido por 60 minutos (configurável via `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`).
- **Refresh token:** válido por 7 dias (configurável via `JWT_REFRESH_TOKEN_LIFETIME_DAYS`).
- Rotação ativada: ao usar refresh, o refresh antigo é invalidado.

## Papéis (RBAC)

| Role | Descrição | Permissões típicas |
|------|-----------|-------------------|
| `admin` | Administrador | Tudo |
| `manager` | Gerente | CRUD de agentes, atribuição manual |
| `agent` | Atendente | Visualização e atendimento |
| `viewer` | Visualizador | Apenas leitura |

### Helpers de permissão

- `require_role(*roles)` — decorator genérico.
- `require_admin` — apenas `admin`.
- `require_manager_or_admin` — `admin` ou `manager`.
- `require_agent_or_above` — `admin`, `manager` ou `agent`.

## Endpoints de autenticação

| Método | Path | Descrição |
|--------|------|-----------|
| POST | `/api/v1/auth/login` | Obtém access + refresh tokens |
| POST | `/api/v1/auth/refresh` | Renova access token |
| POST | `/api/v1/auth/logout` | Invalida refresh token |

## Webhooks

Webhooks do HubSpot e Jira não usam JWT. A autenticação é feita via HMAC:

- HubSpot: `X-HubSpot-Signature` (v1) ou `X-HubSpot-Signature-v3` (v3).
- Jira: `X-Hub-Signature`.

## Arquivos relacionados

- [`apps/auth_user/api.py`](../../apps/auth_user/api.py)
- [`apps/auth_user/services.py`](../../apps/auth_user/services.py)
- [`common/permissions.py`](../../common/permissions.py)
- [`core/settings/base.py`](../../core/settings/base.py)

## Pontos de atenção

- `DJANGO_SECRET_KEY` é usada tanto pelo Django quanto pelo JWT. Rotação invalida todas as sessões.
- Em `DEBUG`, webhooks HubSpot sem `HUBSPOT_APP_SECRET` são aceitos sem assinatura.
- O helper `require_role` verifica `request.auth.role`; se `request.auth` não tiver `role`, levanta `ForbiddenError`.

## Recomendações

- Implementar refresh automático no frontend antes da expiração.
- Considerar RBAC mais granular (permissões por recurso, não só por role).
- Adicionar logs de auditoria para ações sensíveis.
