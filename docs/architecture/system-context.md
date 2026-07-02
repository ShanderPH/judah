# Contexto do Sistema

## Resumo

Este documento descreve o contexto externo do JUDAH: quem interage com o sistema, quais sistemas externos se comunicam com ele e quais são as fronteiras de responsabilidade.

## Contexto

O JUDAH atua como hub central entre canais de atendimento (HubSpot, Jira), infraestrutura de IA (OpenAI, Pinecone), banco de dados (Supabase/PostgreSQL), cache/broker (Redis) e o painel administrativo Next.js.

## Atores

| Ator | Papel | Interação principal |
|------|-------|---------------------|
| Cliente final (membro da igreja) | Abre tickets e conversa com o agente de IA | HubSpot chat/email/form → webhook JUDAH |
| Agente de suporte N1 | Resolve tickets atribuídos | HubSpot CRM / webapp Judah |
| Gerente/Admin | Configura agentes, filas e horários | Webapp Judah (`webapp/`) |
| Sistema legado InChurch | Fornece dados de eventos e diagnóstico | API interna InRadar (`INRADAR_AUTH_TOKEN`) |
| Time de engenharia | Opera, monitora e evolui o backend | Railway, Sentry, logs |

## Sistemas externos

| Sistema | Protocolo | Uso no JUDAH | Arquivos principais |
|---------|-----------|--------------|---------------------|
| HubSpot | REST API + Webhooks (HMAC v1/v3) | CRM, tickets, pipelines, owners, availability | [`apps/integrations/hubspot/`](../../apps/integrations/hubspot/), [`apps/webhooks/handlers/hubspot_handler.py`](../../apps/webhooks/handlers/hubspot_handler.py), [`apps/ai_agents/mcp_servers/hubspot_server.py`](../../apps/ai_agents/mcp_servers/hubspot_server.py) |
| Jira | REST API + Webhooks | Criação/escalonamento de issues técnicas | [`apps/integrations/jira/`](../../apps/integrations/jira/), [`apps/webhooks/handlers/jira_handler.py`](../../apps/webhooks/handlers/jira_handler.py) |
| Pinecone | gRPC/REST | Busca semântica (RAG) | [`apps/integrations/pinecone_client/client.py`](../../apps/integrations/pinecone_client/client.py), [`apps/ai_agents/agents/rag.py`](../../apps/ai_agents/agents/rag.py) |
| Supabase | PostgreSQL + REST | Persistência principal | [`apps/integrations/supabase_client/client.py`](../../apps/integrations/supabase_client/client.py) |
| OpenAI | REST API | LLMs e embeddings | [`apps/ai_agents/agents/base.py`](../../apps/ai_agents/agents/base.py) |
| Anthropic | REST API | Fallback de LLM | [`apps/ai_agents/agents/base.py`](../../apps/ai_agents/agents/base.py) |
| Sentry | SDK | Erros, traces e performance | [`core/settings/base.py`](../../core/settings/base.py) |
| InRadar (InChurch) | REST API | Diagnóstico de eventos | [`apps/ai_agents/tools/inchurch_tools.py`](../../apps/ai_agents/tools/inchurch_tools.py) |
| n8n | Webhooks (MCP SSE placeholder) | Workflows externos | [`apps/ai_agents/agents/action.py`](../../apps/ai_agents/agents/action.py) |

## Fronteiras

- **JUDAH não processa pagamentos:** informações de planos e gateways são mantidas em `apps/church`, mas a cobrança provavelmente ocorre em sistema externo (TODO: confirmar).
- **JUDAH não envia WhatsApp diretamente:** o canal WhatsApp é do HubSpot; o JUDAH reage a tickets e pode criar/atualizar tickets via API.
- **JUDAH não armazena embeddings no Postgres:** embeddings e busca vetorial ficam no Pinecone; Postgres guarda metadados dos artigos.

## Diagrama de contexto

```text
┌─────────────────────────────────────────────────────────────────────┐
│                           JUDAH                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │    API      │  │   Workers   │  │    AI       │  │  WebApp   │  │
│  │   Ninja     │  │   Celery    │  │   Agents    │  │  Next.js  │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬─────┘  │
└─────────┼────────────────┼────────────────┼───────────────┼────────┘
          │                │                │               │
    ┌─────┴─────┐    ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐
    │  HubSpot  │    │   Jira    │   │  OpenAI   │   │  Usuário  │
    │(webhooks) │    │(webhooks) │   │ Pinecone  │   │  (navegador)│
    └───────────┘    └───────────┘   └───────────┘   └───────────┘
          │                │                │
    ┌─────┴─────┐    ┌─────┴─────┐   ┌─────┴─────┐
    │  Redis    │    │  Sentry   │   │  Supabase │
    │(cache/broker)│   │(observability)│  │(Postgres) │
    └───────────┘    └───────────┘   └───────────┘
```

## Arquivos relacionados

- [`apps/integrations/`](../../apps/integrations/): clients de integrações externas.
- [`apps/webhooks/`](../../apps/webhooks/): recebimento e roteamento de webhooks.
- [`webapp/README.md`](../../webapp/README.md): documentação do frontend.

## Pontos de atenção

- A assinatura de webhooks do HubSpot é verificada via HMAC v1 ou v3. Em `DEBUG` sem `HUBSPOT_APP_SECRET`, a verificação é bypassada (risco documentado em [`security/risks.md`](../security/risks.md)).
- A integração InRadar depende de `INRADAR_AUTH_TOKEN`, cuja origem/renovação não está clara no código (TODO: confirmar).
- Servidores MCP adicionais (Jira, n8n, Central de Ajuda) estão configurados como placeholders desabilitados.

## Recomendações

- Documentar formalmente o contrato de cada webhook externo em [`api/examples.md`](../api/examples.md).
- Criar um diagrama C4 de contexto quando o escopo estabilizar.
- Manter um inventário de tokens e secrets com datas de expiração.
