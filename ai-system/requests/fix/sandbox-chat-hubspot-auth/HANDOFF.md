# Handoff

## Resumo do implementado/corrigido

- Corrigido o endpoint e o payload do Visitor Identification API.
- Mantido o access token da sandbox exclusivamente no servidor Next.js.
- Adicionado nome canonico de env com fallback para deployments existentes.
- Adicionada a assinatura `conversation.newMessage` ao projeto local HubSpot.
- Criada rota HMAC isolada `/api/v1/webhooks/hubspot/sandbox/` com secret
  dedicado e validacao v1/v3 conforme o contrato atual da HubSpot.
- Corrigida a validacao v3 preexistente: ordem oficial, Base64 e janela
  antirreplay de cinco minutos.
- Validado o webapp e o schema do projeto HubSpot.

## Arquivos modificados

- `webapp/app/api/hubspot/visitor-token/route.ts`
- `webapp/src/features/sandbox-chat/sandbox-chat.tsx`
- `webapp/README.md`
- `apps/webhooks/api.py`
- `apps/webhooks/tests/test_hubspot_api.py`
- `core/settings/base.py`
- `docs/setup/environment-variables.md`
- `inchurch-sandbox/src/app/webhooks/sandbox-webhooks-hsmeta.json`
- `ai-system/requests/fix/sandbox-chat-hubspot-auth/*`

## Como testar localmente

```powershell
cd webapp
$env:JUDAH_API_URL='http://127.0.0.1:8000/api/v1'
$env:NEXT_PUBLIC_HUBSPOT_PORTAL_ID='51734496'
$env:HUBSPOT_SANDBOX_ACCESS_TOKEN='<private-app-token>'
npm.cmd run dev
```

Autentique no Judah e abra `http://localhost:3000/sandbox-chat`.

## Riscos conhecidos / areas frageis

- Visitor Identification exige conta Professional/Enterprise e o escopo
  `conversations.visitor_identification.tokens.create`.
- O build remoto #7 aponta para a rota dedicada, mas deixa
  `conversation.newMessage` inativo ate a rota existir no Railway.
- O backend Railway e o webapp publicado ainda nao incluem estas mudancas.

## Pontos de integracao criticos

- Publicar um chatflow na sandbox com target para
  `judah-admin.febrate.com/sandbox-chat`.
- Configurar `HUBSPOT_SANDBOX_ACCESS_TOKEN` no deployment do webapp.
- Configurar `HUBSPOT_SANDBOX_APP_SECRET` no backend Railway.
- Depois do deploy, validar que a rota retorna `500` sem secret ou
  `signature_mismatch` com assinatura invalida; somente entao ativar
  `conversation.newMessage` e publicar um novo build HubSpot.
