# Webhooks

Eventos `conversation.newMessage` autenticados são persistidos no ledger,
hidratados pela Conversations API e convergem com a reconciliação no mesmo
serviço atômico. A entrega ao n8n usa `n8n_outbox_events`; nenhuma chamada ao
n8n ocorre durante a requisição HubSpot. Veja
[`architecture/n8n-inbound-adapter.md`](../architecture/n8n-inbound-adapter.md).

`POST /api/v1/webhooks/hubspot/` valida HMAC, persiste cada entrega e devolve
`202` antes do processamento assíncrono. O worker normaliza eventos no ledger e
despacha somente efeitos operacionais válidos:

- entrada no estágio NOVO do pipeline de suporte: autoatribuição;
- fechamento calculado: encerramento do lifecycle;
- alteração de owner: sincronização de atribuição.

O webhook Jira permanece independente. Eventos de mensagens não acionam mais
identificação, triagem, resposta automática ou handoff de bot.
