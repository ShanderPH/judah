# Exemplos de API

## Health

```bash
curl http://localhost:8000/api/v1/health/
```

## Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret"}'
```

## Fila

```bash
curl http://localhost:8000/api/v1/support/queue/status/ \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Webhooks HubSpot devem usar a assinatura HMAC exigida pelo receptor; não use
este exemplo para simular eventos em ambientes compartilhados.
