# Exemplos de Uso da API

## Resumo

Exemplos práticos de requisições e respostas para os principais endpoints da API JUDAH.

## Contexto

Os exemplos assumem a API rodando em `http://localhost:8000/api/v1`. Substitua o token JWT pelos valores reais.

---

## Login

### Requisição

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "usuario@inchurch.com.br",
    "password": "senhaSegura123"
  }'
```

### Resposta

```json
{
  "access": "eyJhbGciOiJIUzI1NiIs...",
  "refresh": "eyJhbGciOiJIUzI1NiIs..."
}
```

---

## Perfil do usuário

### Requisição

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### Resposta

```json
{
  "id": 1,
  "username": "usuario@inchurch.com.br",
  "email": "usuario@inchurch.com.br",
  "first_name": "Fulano",
  "last_name": "Silva",
  "role": "manager",
  "avatar_url": null,
  "is_ai_agent": false
}
```

---

## Status da fila

### Requisição

```bash
curl http://localhost:8000/api/v1/support/queue/status/ \
  -H "Authorization: Bearer <access_token>"
```

### Resposta

```json
{
  "online_agents": 3,
  "eligible_agents": 2,
  "pending_queue_depth": 5,
  "agents": [
    {
      "id": "uuid",
      "name": "Ana Souza",
      "hubspot_owner_id": 123456,
      "status": "online",
      "current_chats": 2,
      "max_chats": 5,
      "last_assignment_at": "2026-07-02T10:00:00Z"
    }
  ]
}
```

---

## Sincronizar tickets NOVO

### Requisição

```bash
curl -X POST http://localhost:8000/api/v1/support/queue/sync-novo/
```

### Resposta

```json
{
  "created": 3,
  "skipped": 10,
  "already_assigned": 2,
  "total_from_hubspot": 15,
  "queued_for_assignment": true,
  "error": null
}
```

---

## Busca semântica

### Requisição

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/search/ \
  -H "Content-Type: application/json" \
  -d '{
    "query": "como redefinir senha",
    "top_k": 3
  }'
```

### Resposta

```json
[
  {
    "article_id": 1,
    "title": "Como redefinir sua senha",
    "summary": "Passo a passo para redefinir...",
    "score": 0.89,
    "url": null
  }
]
```

---

## Chat com Salomão

### Requisição

```bash
curl -X POST http://localhost:8000/api/v1/ai/salomao/chat \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Não consigo emitir boleto"
  }'
```

### Resposta

```json
{
  "session_id": "user-1",
  "message": "Olá! 👋 Eu sou o Salomão... Entendi que você não consegue emitir o boleto. Vou verificar isso para você.",
  "sources": [],
  "requires_human_handoff": false,
  "handoff_reason": null,
  "agent_trace": ["Heimdall: OK"],
  "tokens_used": 150,
  "latency_ms": 1200
}
```

> Nota: endpoint só disponível quando `AI_ROUTING_ENABLED=true`.

---

## Criar agente (manager/admin)

### Requisição

```bash
curl -X POST http://localhost:8000/api/v1/support/agents/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Carlos Lima",
    "agent_email": "carlos@inchurch.com.br",
    "hubspot_owner_id": 987654,
    "max_simultaneous_chats": 4
  }'
```

### Resposta

```json
{
  "id": "uuid",
  "name": "Carlos Lima",
  "agent_email": "carlos@inchurch.com.br",
  "hubspot_owner_id": 987654,
  "status_enum": "offline",
  "current_simultaneous_chats": 0,
  "max_simultaneous_chats": 4,
  "auto_assign_enabled": true,
  "is_active": true,
  "timezone": "America/Sao_Paulo"
}
```

---

## Receber webhook HubSpot

### Requisição

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/hubspot/ \
  -H "Content-Type: application/json" \
  -H "X-HubSpot-Signature-v3: <assinatura>" \
  -d '[{
    "eventId": 1,
    "subscriptionType": "ticket.propertyChange",
    "objectId": 123456789,
    "propertyName": "hs_v2_date_entered_939275049",
    "propertyValue": "1720000000000"
  }]'
```

### Resposta

```json
{
  "status": "accepted",
  "events_queued": 1,
  "events_received": 1
}
```

---

## Arquivos relacionados

- [`api/endpoints.md`](./endpoints.md)
- [`api/authentication.md`](./authentication.md)
