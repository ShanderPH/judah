# Glossário de Domínio

## Resumo

Termos do negócio usados no JUDAH e sua explicação no contexto do sistema.

## Glossário

### Agente (support)

Atendente humano do suporte N1 da InChurch. Representado por `apps.support.models.Agent`, mapeado a um `hubspot_owner_id`. Possui status (`online`, `away`, `offline`, `busy`), capacidade máxima de chats simultâneos e contadores de atribuição.

### Agente de IA

Sistema de inteligência artificial que atende clientes. No JUDAH, o ecossistema é chamado **Salomão** e é composto por sub-agentes (Heimdall, KnowledgeRagAgent, HelpdeskActionAgent).

### Backoffice

Sistema legado de administração substituído pelo JUDAH.

### Central de Ajuda

Canal de atendimento via webchat da InChurch. Mensagens da central não devem disparar ações no HubSpot porque não há ticket ativo.

### ClosedConversation

Registro de ticket fechado pelo sistema de auto-atribuição. Guarda métricas como tempo de espera e tempo de handle.

### Customer Success (CS)

Filial de atendimento para onboarding, renovação, upsell e reuniões estratégicas. Uma das rotas do Heimdall.

### DUVIDAS_PLATAFORMA

Rota do Heimdall para dúvidas operacionais respondíveis pela base de conhecimento.

### ESCALAR_IMEDIATAMENTE

Rota do Heimdall para casos que devem ir direto a um atendente humano (insultos, ameaça de processo, caixa alta agressiva, etc.).

### Heimdall

Agente de triagem que classifica mensagens e define rota, prioridade, tags, dados faltantes e sentimento.

### Helper CX

Sistema legado de helpdesk substituído pelo JUDAH.

### HubSpot Owner ID

Identificador numérico de um usuário/agente no HubSpot CRM. Usado para atribuir tickets e mapear agentes locais.

### Knowledge Base (KB)

Base de conhecimento com artigos da InChurch, sincronizada do HubSpot CMS e indexada semanticamente no Pinecone.

### Matchmaker

Serviço de atribuição automática que consome a fila `new_conversations` e seleciona o melhor agente disponível.

### MCP (Model Context Protocol)

Protocolo para conectar agentes de IA a ferramentas externas (HubSpot, Jira, n8n). O JUDAH implementa um servidor FastMCP para HubSpot.

### NewConversation

Ticket que entrou no estágio NOVO do pipeline e aguarda atribuição automática.

### NOVO

Estágio inicial do pipeline de suporte no HubSpot (`939275049`). Tickets neste estágio são candidatos à auto-atribuição.

### Pinecone

Vector store usado para busca semântica (RAG) sobre a base de conhecimento.

### Pipeline de suporte

Pipeline HubSpot (`636459134`) usado para tickets de suporte da InChurch. Contém estágios como NOVO (`939275049`) e FECHADO (`939275052`).

### Quinta Fire

Janela de reunião semanal da InChurch às quintas-feiras entre 12h e 13h. Fora do horário de atendimento.

### RAG (Retrieval-Augmented Generation)

Técnica usada pelo KnowledgeRagAgent: recupera artigos relevantes do Pinecone e gera resposta baseada neles.

### Salomão

Assistente virtual de suporte da InChurch. Supervisor multi-agente que orquestra Heimdall, RAG e Action.

### SAT (Smart Agent Tracking)

Sistema de rastreamento de disponibilidade de agentes. Faz heartbeat de 20s consultando availability no HubSpot e dispara Matchmaker quando agentes ficam online.

### SUPORTE_TECNICO_N1

Rota do Heimdall para bugs, erros, travamentos e problemas técnicos.

### TokenTrackingLog

Registro de consumo de tokens e custo por execução do pipeline de IA.

### Transbordo

Transferência do atendimento da IA para um humano. Pode ser sinalizado pelo Heimdall (`ESCALAR_IMEDIATAMENTE`) ou pelo RAG (`<REQUIRES_ESCALATION>`).

## Arquivos relacionados

- [`business/business-rules.md`](./business-rules.md)
- [`business/workflows.md`](./workflows.md)
- [`services/ai_agents.md`](../services/ai_agents.md)
- [`services/support.md`](../services/support.md)
