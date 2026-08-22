# Webhooks

`POST /api/v1/webhooks/hubspot/` valida HMAC, persiste cada entrega e devolve
`202` antes do processamento assíncrono. O worker normaliza eventos no ledger e
despacha somente efeitos operacionais válidos:

- entrada no estágio NOVO do pipeline de suporte: autoatribuição;
- fechamento calculado: encerramento do lifecycle;
- alteração de owner: sincronização de atribuição.

O webhook Jira permanece independente. Eventos de mensagens não acionam mais
identificação, triagem, resposta automática ou handoff de bot.
