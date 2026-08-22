# Integrações

## HubSpot

O cliente compartilhado mantém tickets, owners, equipes, propriedades,
associações e operações usadas por filas, atribuição e métricas. Os manifests
versionados assinam somente eventos operacionais necessários; a publicação do
manifest exige uma operação externa separada.

## Supabase/PostgreSQL

É a persistência compartilhada de lifecycle, filas, agentes, calendário,
auditoria e métricas. A remoção legada não apaga tabelas ou histórico.

## Salomão, Pinecone e knowledge

O cliente Salomão v1, o RAG e a base de conhecimento são capacidades
independentes. Não são ponto de entrada para identificação ou triagem.

## Jira

O webhook e o cliente Jira permanecem disponíveis aos fluxos de tickets que não
dependem da implementação removida.
