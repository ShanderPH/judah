> [Índice completo](../INDEX.md)

# Visão Geral de Segurança

## Autenticação

- JWT com HS256.
- Tokens rotacionados na renovação e invalidados no logout.
- Senhas gerenciadas pelo Django (`AbstractUser`).

## Autorização

- RBAC com papéis: admin, manager, agent, viewer.
- Decorators em `common/permissions.py` protegem endpoints.

## Webhooks

- HubSpot: HMAC v1 e v3 validados.
- HubSpot v3: digest Base64, URI normalizada e janela antirreplay de cinco
  minutos.
- Jira: `X-Hub-Signature` validada.
- Em `DEBUG`, validação pode ser relaxada se `HUBSPOT_APP_SECRET` não estiver configurado.
- Fora de `DEBUG`, a ausência do segredo falha fechado.

## Conteúdo e efeitos de IA

- Conteúdo do cliente é sanitizado e limitado antes de entrar no prompt.
- Tentativas explícitas de sobrescrever instruções geram handoff antes do LLM.
- Tools externas são autorizadas pelo estado e pelo `ConversationContext`.
- Cada efeito usa chave de idempotência e `ToolCallAuditLog`.
- Snapshots de auditoria usam hashes e tamanhos para evitar duplicar PII.

## Segredos

| Variável | Uso |
|----------|-----|
| `DJANGO_SECRET_KEY` | Assinatura de sessões e JWT |
| `OPENAI_API_KEY` | API da OpenAI |
| `PINECONE_API_KEY` | Vetor database |
| `HUBSPOT_ACCESS_TOKEN` | API HubSpot |
| `HUBSPOT_APP_SECRET` | Validação de webhooks HubSpot |

## Headers de segurança

- `SECURE_SSL_REDIRECT` está **deliberadamente desabilitado** em produção (`core/settings/production.py`), porque a Railway termina TLS na edge e o health check interno não envia `X-Forwarded-Proto`. O redirecionamento HTTPS é feito pela própria Railway.
- `SECURE_PROXY_SSL_HEADER` configurado para confiar no header `X-Forwarded-Proto` da Railway.
- CSRF habilitado para views Django normais.

## Arquivos relacionados

- [`api/authentication.md`](../api/authentication.md)
- [`setup/environment-variables.md`](../setup/environment-variables.md)
