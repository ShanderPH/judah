# `apps.knowledge` — Base de Conhecimento

## Resumo

Módulo responsável pela base de conhecimento da InChurch: categorias, artigos, chunks e busca semântica via Pinecone.

## Contexto

A base de conhecimento é sincronizada do HubSpot CMS e indexada semanticamente no Pinecone para uso pelo KnowledgeRagAgent. O Postgres armazena metadados dos artigos e chunks.

## Responsabilidades

- Armazenar artigos e categorias.
- Indexar chunks para RAG.
- Disponibilizar busca semântica.
- Registrar logs de sincronização.

## Modelos

### `Category`

Categorias de artigos. Mapeia `kb_categories`.

### `Article`

Artigos da base de conhecimento. Mapeia `kb_articles`.

| Campo | Descrição |
|-------|-----------|
| `hubspot_id` | ID do artigo no HubSpot (único) |
| `title`, `slug`, `body_html`, `body_plain`, `summary` | Conteúdo |
| `state` | Estado (ex: `PUBLISHED`) |
| `category_hubspot_id` | Categoria no HubSpot |
| `tags`, `tag_ids` | Metadados |
| `synced_at` | Última sincronização |

### `ArticleChunk`

Chunks de artigos para RAG. Mapeia `kb_article_chunks`.

| Campo | Descrição |
|-------|-----------|
| `article` | FK para Article |
| `article_hubspot_id` | ID do artigo no HubSpot |
| `pinecone_id` | ID no Pinecone (único) |
| `chunk_index` | Índice do chunk |
| `chunk_text` | Texto do chunk |
| `token_count` | Tokens estimados |

### `KBSyncLog`

Log de sincronização da base de conhecimento.

## Endpoints

Base: `/api/v1/knowledge/`

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| GET | `/articles/` | JWT | Lista artigos publicados (paginado) |
| GET | `/articles/{slug}` | JWT | Detalhe de um artigo |
| POST | `/search/` | — | Busca semântica |

## Services principais

- `list_published_articles(category_slug)`: lista artigos `PUBLISHED`, opcionalmente filtrados por categoria.
- `get_article_by_slug(slug)`: busca artigo publicado.
- `semantic_search(query, top_k, category_slug)`: faz embedding da query via OpenAI e busca no Pinecone.

## Regras de negócio

- Apenas artigos `state=PUBLISHED` são listados publicamente.
- Busca semântica usa `text-embedding-3-small` (hard-coded em `apps/integrations/pinecone_client/client.py`); a variável `EMBEDDING_MODEL` não é consultada por esse client.
- Se Pinecone falhar, retorna lista vazia (não quebra a requisição).

## Arquivos relacionados

- [`apps/knowledge/models.py`](../../apps/knowledge/models.py)
- [`apps/knowledge/api.py`](../../apps/knowledge/api.py)
- [`apps/knowledge/services.py`](../../apps/knowledge/services.py)
- [`apps/integrations/pinecone_client/client.py`](../../apps/integrations/pinecone_client/client.py)

## Pontos de atenção

- Não há endpoint, task ou comando de gerenciamento de sincronização com HubSpot exposto no app `knowledge` atualmente.
- O schema `ArticleResponse` espera campos como `status` e `helpful_count`, mas o modelo usa `state` e não tem `helpful_count`. Isso pode causar inconsistência na serialização.

## Recomendações

- Alinhar schema `ArticleResponse` com o modelo.
- Adicionar endpoint de sincronização e testes.
