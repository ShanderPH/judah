> [Índice completo](../INDEX.md)

# Recomendações de Segurança

## Curtas prazo

1. **Garantir `debug_mode=False` em produção** para agentes de IA.
2. **Auditar sintaxe de exceções** em `apps/support/services.py`, `auto_assign_service.py` e `hubspot_handler.py` (a correção principal em `services.py` já foi aplicada).
3. **Adicionar rate limiting** nos endpoints de IA (`/api/v1/ai/*`).
4. **Revisar logs** para não imprimir tokens, chaves ou payloads completos de webhooks.

## Médio prazo

1. **Implementar RBAC granular** com permissões por recurso.
2. **Adicionar audit logging** para ações sensíveis (atribuição, reatribuição, exclusão).
3. **Configurar CORS** restrictivamente em produção.
4. **Ativar 2FA** para usuários admin/manager.

## Longo prazo

1. **Migrar para RS256** para JWT, permitindo rotação de chaves sem invalidar todos os tokens.
2. **Implementar mTLS** para comunicação entre serviços internos.
3. **Revisão de segurança periódica** (pentest/análise estática).

## Arquivos relacionados

- [`security/risks.md`](./risks.md)
- [`security/overview.md`](./overview.md)
