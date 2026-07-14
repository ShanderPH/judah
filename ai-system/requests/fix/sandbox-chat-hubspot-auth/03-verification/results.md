# Verification results

## Webapp

```text
npm run lint  -> PASS
npm run build -> PASS
```

O build confirmou a Route Handler dinamica
`/api/hubspot/visitor-token` e a pagina dinamica `/sandbox-chat`.

## HubSpot project

```text
HubSpotDev validate_project -> SUCCESS
```

O build #6 publicou o novo target e `conversation.newMessage`, mas o smoke test
do target retornou 404 porque o backend ainda nao contem a rota nova. Para
evitar retries, o build #7 foi publicado com a assinatura temporariamente
inativa. Ambos os builds terminaram com `SUCCESS`.

## Backend

```text
uv run ruff check ...       -> PASS
uv run python run_tests_local.py -> 371 passed
uv run mypy ...             -> BLOCKED pelo plugin Django do mypy 2.1.0
```

Os testes usaram o SQLite privado configurado por `run_tests_local.py`.

## Producao

- `GET /sandbox-chat` sem sessao retorna `307` para o login esperado.
- `POST /api/hubspot/visitor-token` sem sessao retorna `401` esperado.
- Nao havia browser autenticado disponivel para repetir o fluxo visual.
- `POST /api/v1/webhooks/hubspot/sandbox/` no Railway retorna `404` ate o
  deploy das mudancas locais.
