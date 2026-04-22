# KnowledgeRagAgent - Implementação RAG com AgentKnowledge (Agno 2.5 + Pinecone)

## Resumo

Implementação refatorada do agente RAG usando a API nativa `AgentKnowledge` do Agno 2.5, com injeção de base de conhecimento via parâmetro `knowledge` e busca automática habilitada.

## Arquivos Modificados

- `apps/ai_agents/agents/rag.py` - Agente refatorado com AgentKnowledge

## Arquitetura Agno 2.5

### 1. AgentKnowledge + VectorDB

```python
from agno.knowledge.agent import AgentKnowledge
from agno.vectordb.pinecone import Pinecone

# Cria VectorDB Pinecone
vector_db = Pinecone(
    name=index_name,
    dimension=1536,
    metric="cosine",
    api_key=api_key,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

# Cria AgentKnowledge
knowledge_base = AgentKnowledge(vector_db=vector_db)
```

### 2. Injeção no Agente

```python
super().__init__(
    ...
    knowledge=knowledge_base,      # Injeta a base de conhecimento
    search_knowledge=True,         # Ativa busca automática
    ...
)
```

### 3. System Prompt (Especialista de Produto)

O agente agora usa um prompt rigoroso que define:
- **Função única**: Responder dúvidas técnicas baseadas na documentação oficial
- **Protocolo obrigatório**: SEMPRE buscar na base antes de responder
- **Regra anti-hallucination**: Se a informação não estiver nos documentos, NÃO INVENTE
- **Citação obrigatória**: "Com base na documentação oficial da InChurch..."
- **Fallback**: Sugerir ticket para suporte humano quando não houver documentação

## Componentes

### `_create_knowledge_base()`
Cria a instância de `AgentKnowledge` vinculada ao Pinecone usando variáveis de ambiente:
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `PINECONE_HOST` (opcional)

### `KnowledgeSearchTool`
Ferramenta auxiliar para buscas complementares e recuperação de artigos específicos:
- `search_knowledge_base()` - Busca manual com score threshold
- `get_article_by_id()` - Recupera artigo específico

### Tratamento de Erros
Respostas estruturadas para diferentes cenários:
- `status: unavailable` - Configuração ausente ou indisponível
- `status: error` - Erro genérico na busca
- `status: not_found` - Artigo não encontrado
- `status: success` - Busca bem-sucedida

## Variáveis de Ambiente

```bash
PINECONE_API_KEY=pcsk_...               # Chave de API do Pinecone
PINECONE_INDEX_NAME=inchurch-knowledge  # Nome do índice
PINECONE_HOST=https://...               # Host do índice (opcional)
```

## Segurança

- Nenhum acesso ao Django ORM dentro do agente
- Credenciais estritamente via `os.getenv` (sem `django.conf.settings`)
- Logging estruturado via structlog (sem expor secrets)

## Dependências

- `agno>=2.5.0` - Framework de agentes
- `pinecone>=6.0.0` - Cliente Pinecone
- `openai>=1.60.0` - Para embeddings

## Uso

```python
from apps.ai_agents.agents.rag import KnowledgeRagAgent

agent = KnowledgeRagAgent(
    session_id="user-123-session",
    user_metadata={"user_id": 123, "email": "user@igreja.com"}
)

# O Agno automaticamente:
# 1. Busca documentos relevantes no Pinecone via search_knowledge=True
# 2. Injeta o contexto no prompt
# 3. Gera resposta citando a fonte
```

## Diferenças da Implementação Anterior

| Aspecto | Antes | Agora |
|---------|-------|-------|
| Busca | Manual via Toolkit | Automática via `search_knowledge=True` |
| Knowledge | Toolkit standalone | `AgentKnowledge` injetado no agente |
| Prompt | Instruções em lista | String única com diretrizes rigorosas |
| Fallback | Genérico | Específico com sugestão de ticket |
| Citação | Recomendada | Obrigatória e estruturada |
