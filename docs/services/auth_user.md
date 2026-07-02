# `apps.auth_user` — Autenticação e Usuários

## Resumo

Módulo responsável pela identidade, autenticação e autorização no JUDAH. Define o modelo customizado de usuário, endpoints de login/logout/registro e permissões baseadas em papéis.

## Contexto

O JUDAH não usa o `User` padrão do Django. O modelo `apps.auth_user.models.User` estende `AbstractUser` com campos específicos do domínio (`role`, `avatar_url`, `hubspot_owner_id`, `is_ai_agent`).

## Responsabilidades

- Cadastro de usuários.
- Login com username ou email.
- Emissão e rotação de tokens JWT.
- Blacklist de refresh tokens.
- Perfil e alteração de senha.
- Permissões baseadas em roles.

## Modelo

### `User`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `role` | CharField(choices) | `admin`, `manager`, `agent`, `viewer` |
| `avatar_url` | URLField | Foto do perfil |
| `hubspot_owner_id` | CharField | ID do owner no HubSpot |
| `is_ai_agent` | BooleanField | Indica se é agente de IA |
| `created_at` / `updated_at` | DateTimeField | Timestamps |

Tabela: `auth_users`.

## Endpoints

Base: `/api/v1/auth/`

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| POST | `/register` | — | Cria usuário |
| POST | `/login` | — | Retorna access + refresh tokens |
| POST | `/refresh` | — | Gera novo access token |
| POST | `/logout` | — | Blacklista refresh token |
| GET | `/me` | JWT | Perfil do usuário logado |
| PATCH | `/me` | JWT | Atualiza perfil |
| POST | `/me/change-password` | JWT | Altera senha |
| GET | `/{user_id}` | JWT | Busca usuário por ID |

## Services principais

- `register_user(payload)`: valida duplicidade de username/email e cria usuário.
- `authenticate_user(identifier, password)`: busca por username ou email (case-insensitive) e valida senha.
- `change_password(user, payload)`: exige `current_password` correta.

## Regras de negócio

- Username e email devem ser únicos.
- Senha deve ter ≥ 8 caracteres, 1 letra e 1 dígito.
- Login por email é case-insensitive.
- JWT usa HS256 com `DJANGO_SECRET_KEY`.

## Arquivos relacionados

- [`apps/auth_user/models.py`](../../apps/auth_user/models.py)
- [`apps/auth_user/api.py`](../../apps/auth_user/api.py)
- [`apps/auth_user/services.py`](../../apps/auth_user/services.py)
- [`apps/auth_user/schemas.py`](../../apps/auth_user/schemas.py)
- [`apps/auth_user/admin.py`](../../apps/auth_user/admin.py)

## Pontos de atenção

- A rotação de `DJANGO_SECRET_KEY` invalida todos os tokens ativos.
- O login pode retornar 503 se houver falha na blacklist do JWT (tabela não migrada).

## Recomendações

- Considerar rate limit específico em `/auth/login`.
- Adicionar 2FA para admins no futuro.
