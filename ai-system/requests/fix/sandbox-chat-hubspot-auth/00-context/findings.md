# Findings

## Sintoma

`https://judah-admin.febrate.com/sandbox-chat` exibe
`Nao foi possivel autenticar o visitante no HubSpot.` depois que uma sessao
Judah autenticada solicita um token de identificacao.

## Causa raiz confirmada

- A Route Handler chamava um endpoint inexistente para este contrato:
  `/conversations/v3/visitor-identification/tokens`.
- O payload usava `visitorId` e `expiresInMins`; o Visitor Identification API
  requer `email` e aceita nome/contexto do visitante.
- O endpoint oficial validado e
  `POST https://api.hubapi.com/visitor-identification/v3/tokens/create`.

## Estado HubSpot validado pelo MCP

- App remoto: `inchurch-sandbox-App`, app ID `45639385`.
- Projeto `inchurch-sandbox`: valido.
- Builds remotos 1 a 4: `SUCCESS`.
- O app declara `conversations.visitor_identification.tokens.create`.
- A configuracao de webhooks nao declarava `conversation.newMessage`, embora
  o backend dependa desse evento para disparar o pipeline do Salomao.

## Configuracao do widget

- Portal: `51734496`, hublet `na1`; o script publico oficial responde.
- O frontend configura `loadImmediately: false`, `inlineEmbedSelector`,
  `identificationEmail` e `identificationToken` antes de carregar o widget.
- O chatflow precisa estar publicado na sandbox e segmentado para o dominio
  `judah-admin.febrate.com` e a rota `/sandbox-chat`.

## Risco de integracao pendente

O endpoint canonico valida webhooks com um unico `HUBSPOT_APP_SECRET`. O app
sandbox tem secret proprio. Trocar essa variavel pelo secret da sandbox pode
interromper webhooks do app de producao; aceitar dois secrets ou criar um
endpoint dedicado altera verificacao HMAC e exige pre-aprovacao.
