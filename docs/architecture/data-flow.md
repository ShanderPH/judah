# Fluxos de dados

## Entrada operacional HubSpot

```text
HubSpot -> /api/v1/webhooks/hubspot/
        -> validação HMAC
        -> WebhookEvent persistido/idempotente
        -> normalização no lifecycle
        -> NOVO: fila + Matchmaker
        -> FECHADO: fechamento do ciclo
        -> owner: sincronização operacional
```

Mensagens de Conversations, se recebidas por compatibilidade de transporte,
são apenas registradas no ledger e não acionam bot, identificação ou triagem.
Os manifests versionados não assinam mais esses eventos.

## Atribuição

```text
new_conversations -> elegibilidade/calendário/capacidade
                  -> claim idempotente
                  -> hubspot_owner_id
                  -> assigned_conversations + métricas
```

## Boundary futuro

O n8n futuramente coletará dados, confirmará identidade, fará triagem e produzirá
uma decisão. A ingestão durável e o lifecycle continuarão no JUDAH. O contrato e
o transporte dessa decisão serão definidos em outra etapa.
