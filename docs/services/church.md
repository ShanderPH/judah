# `apps.church` — Igrejas e Planos

## Resumo

Módulo de domínio das igrejas clientes da InChurch. Mantém informações cadastrais, plano de assinatura e gateway de pagamento.

## Contexto

Cada `Church` representa uma organização (igreja) que usa a plataforma InChurch. O módulo é leitura-dominante no backend; a criação/atualização provavelmente ocorre via integração legada ou admin.

## Responsabilidades

- Armazenar dados cadastrais de igrejas.
- Relacionar igrejas a planos (`Plan`) e gateways (`Gateway`).
- Disponibilizar listagem e detalhes via API.

## Modelos

### `Plan`

| Campo | Descrição |
|-------|-----------|
| `name` | Nome do plano |
| `slug` | Identificador único |
| `max_members` | Limite de membros |
| `is_active` | Plano ativo |

### `Gateway`

| Campo | Descrição |
|-------|-----------|
| `name` / `slug` | Nome e identificador |
| `is_active` | Gateway ativo |

### `Church`

| Campo | Descrição |
|-------|-----------|
| `external_id` | ID externo InChurch (único) |
| `name`, `email`, `phone`, `city`, `state`, `country` | Dados cadastrais |
| `plan` | FK para `Plan` |
| `gateway` | FK para `Gateway` |
| `hubspot_company_id` | ID da empresa no HubSpot |
| `is_active` | Igreja ativa |

## Endpoints

Base: `/api/v1/church/`

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| GET | `/` | JWT | Lista igrejas ativas (paginado) |
| GET | `/{church_id}` | JWT | Detalhe de uma igreja |

## Services principais

- `list_active_churches()`: retorna igrejas ativas ordenadas por nome.
- `get_church_by_id(church_id)`: busca por PK com `select_related`.
- `get_church_by_external_id(external_id)`: busca por ID externo.

## Arquivos relacionados

- [`apps/church/models.py`](../../apps/church/models.py)
- [`apps/church/api.py`](../../apps/church/api.py)
- [`apps/church/services.py`](../../apps/church/services.py)
- [`apps/church/schemas.py`](../../apps/church/schemas.py)

## Pontos de atenção

- Não há endpoints de criação/edição de igrejas na API pública.
- `plan` e `gateway` são FKs nulas; uma igreja pode existir sem plano/gateway definido.

## Recomendações

- Adicionar endpoints administrativos se o webapp precisar gerenciar igrejas.
- Sincronizar `hubspot_company_id` via integração.
