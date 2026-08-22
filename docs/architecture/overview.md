# Visão arquitetural

O fluxo confiável de mensagens HubSpot para n8n está documentado em
[`n8n-inbound-adapter.md`](./n8n-inbound-adapter.md).

JUDAH é o backend operacional do Help Desk InChurch. Django Ninja expõe a API,
PostgreSQL/Supabase mantém o estado compartilhado e Celery executa trabalho
assíncrono. Redis atende cache, locks e broker.

## Responsabilidades atuais

- ingestão durável e idempotente de eventos externos;
- lifecycle e auditoria de ciclos de atendimento;
- filas, Matchmaker, atribuição e capacidade dos agentes;
- status, disponibilidade, calendário e horário de atendimento;
- métricas operacionais;
- leitura e atualização operacional de tickets e owners no HubSpot;
- integrações compartilhadas com Jira, Supabase, Pinecone e Salomão;
- RAG e base de conhecimento independentes.

Identificação de clientes e triagem não são executadas pelo JUDAH. O n8n será
responsável por essas decisões em uma etapa futura. Não existe, no estado atual,
contrato, webhook, outbox, reconciliação ou endpoint para essa integração.
