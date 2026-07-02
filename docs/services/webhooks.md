# `apps.webhooks` — Recebimento de Webhooks

## Resumo

Módulo responsável por receber, validar assinatura, persistir e rotear webhooks inbound do HubSpot e Jira.

## Contexto

O JUDAH é o ponto de entrada canônico para webhooks. Todo evento é persistido em `WebhookEvent` antes do processamento, garantindo auditabilidade e possibilidade de replay.

## Responsabilidades

- Receber webhooks de HubSpot e Jira.
- Verificar assinaturas HMAC (v1/v3 para HubSpot, sha256 para Jira).
- Persistir eventos brutos.
- Rotear para handlers apropriados.
- Gerenciar retries e dead letter queue.

## Modelos

### `WebhookEvent`

| Campo | Descrição |
|-------|-----------|
| `event_type` | Tipo do evento (ex: `ticket.propertyChange`) |
| `event_id` | ID do evento enviado pela origem |
| `object_id` | ID do objeto afetado |
| `property_name` / `property_value` | Propriedade alterada (HubSpot) |
| `payload` | JSON bruto |
| `processed` / `processed_at` | Estado de processamento |
| `retry_count` / `error_message` | Retry e erro |

### `DeadLetterQueue`

Eventos que falharam após `MAX_RETRIES` (3).

## Endpoints

Base: `/api/v1/webhooks/`

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| POST | `/hubspot/` | — | Recebe webhooks do HubSpot |
| POST | `/jira/` | — | Recebe webhooks do Jira |

## Validação de assinatura

### HubSpot v1

```text
X-HubSpot-Signature = SHA-256(client_secret + body)
```

### HubSpot v3

```text
X-HubSpot-Signature-v3 = HMAC-SHA256(timestamp + method + url + body)
```

### Jira

```text
X-Hub-Signature = sha256=<HMAC-SHA256(body)>
```

## Roteamento

- Eventos `ticket.*`, `contact.*`, `deal.*`, `company.*`, `conversation.*` → `hubspot_handler`.
- Outros eventos → tentativa de `jira_handler`.

## Regras de negócio

- Eventos são sempre persistidos, mesmo com assinatura inválida.
- Em produção, sem secret configurado, o endpoint retorna 500 (HubSpot) ou 401 (Jira).
- Em `DEBUG` sem secret, a assinatura é bypassada.
- Após 3 falhas, o evento vai para `DeadLetterQueue`.

## Arquivos relacionados

- [`apps/webhooks/api.py`](../../apps/webhooks/api.py)
- [`apps/webhooks/services.py`](../../apps/webhooks/services.py)
- [`apps/webhooks/handlers/hubspot_handler.py`](../../apps/webhooks/handlers/hubspot_handler.py)
- [`apps/webhooks/handlers/jira_handler.py`](../../apps/webhooks/handlers/jira_handler.py)

## Pontos de atenção

- Existem dois pontos de entrada para webhooks HubSpot: `/api/v1/webhooks/hubspot/` (canônico) e `/api/v1/ai/webhooks/hubspot/ticket-change` (IA). Isso pode causar duplicidade quando `AI_ROUTING_ENABLED=true` (risco C4 no README).
- O handler Jira atual apenas loga eventos; não há integração funcional além de criação manual via service.

## Recomendações

- Consolidar os dois endpoints HubSpot.
- Implementar processamento real de eventos Jira.
- Adicionar UI/admin para visualizar `DeadLetterQueue`.
