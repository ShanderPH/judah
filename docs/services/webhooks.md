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
| POST | `/hubspot/sandbox/` | — | Alias de sandbox com a mesma validação e o mesmo roteamento |
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
- Toda mudança de propriedade de ticket recebida é persistida e registrada nos logs.
- `hs_pipeline_stage=HUBSPOT_SUPPORT_NEW_STAGE_ID` dispara o Matchmaker de atribuição automática.
- `hs_pipeline_stage=HUBSPOT_N1_NEW_STAGE_ID` dispara o Supervisor com Salomão quando a IA está habilitada.
- `hs_last_message_from_visitor` retoma o Supervisor para a próxima fala do cliente, mantendo conversas de múltiplos turnos.
- O worker move o ticket para `HUBSPOT_AI_TRIAGE_STAGE_ID` enquanto processa e para `HUBSPOT_AI_WAITING_STAGE_ID` após enviar a resposta.
- Falha de envio, canal sem resposta automática ou transbordo move o ticket para `HUBSPOT_HUMAN_ESCALATION_STAGE_ID`.
- Estágios não configurados não alteram o status local nem executam tarefas com efeito colateral.

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

- O endpoint canônico é `/api/v1/webhooks/hubspot/`. O arquivo `apps/ai_agents/api/webhooks.py` define `/hubspot/ticket-change`, mas esse router **não está montado** em `core/urls.py`, mesmo quando `AI_ROUTING_ENABLED=true`.
- O handler Jira atual apenas loga eventos; não há integração funcional além de criação manual via service.

## Recomendações

- Consolidar os dois endpoints HubSpot.
- Implementar processamento real de eventos Jira.
- Adicionar UI/admin para visualizar `DeadLetterQueue`.
