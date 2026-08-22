# Lifecycle e IA independente

O app `ai_agents` mantém o ledger durável, a máquina de estados genérica,
auditoria, ciclos de serviço e o watchdog de estados operacionais parados.

Estados preservados cobrem recebimento, normalização, contexto, serviço de IA
independente, espera pelo cliente, handoff humano, fila, atribuição, resolução,
fechamento e falhas. Estados exclusivos de coleta de contato e triagem foram
removidos.

O app não expõe endpoints. A única task própria agendada é
`ai_agents.run_lifecycle_watchdog_task`. RAG, base de conhecimento e o adaptador
Salomão v1 permanecem independentes e não fazem identificação ou triagem.

Não há classifier, Supervisor, agente Heimdall, MCP de ações HubSpot ou retry de
pipeline legado.
