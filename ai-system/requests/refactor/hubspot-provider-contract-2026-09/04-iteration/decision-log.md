# Decisões e limites da implementação local

- `INT-05` Journal: **not adopted** nesta etapa. A capability e a semântica de replay não foram comprovadas no sandbox; webhook + CRM readback + retry bounded continuam a base do P0.
- `INT-06` Conversations: **not adopted** nesta etapa. Ainda não há prova de correlação thread ↔ ticket 1:1, actor e transferências na conta. Não cria ciclo a partir de thread.
- `tickets_write` no preflight: leitura não prova permissão de PATCH. Fica `unverified` até mutation sandbox autorizada e flag operacional `HUBSPOT_TICKETS_WRITE_VERIFIED` explícita.
- `shadow`: persiste ocorrência e passa pelo writer canônico de ciclo, mas mantém projeções/controles legados de `off`. Requer comparação operacional antes de `enforce`.
- O adapter versionado de Tickets está selecionado apenas em `enforce`; outros métodos legados do SDK continuam para busca e workflows fora do escopo imediato. Não declarar migração completa da API.
- `enforce` exige `SUPPORT_CAPACITY_MODE=enforce`, pois o handler de owner só delega integralmente ao reconciliador nessa combinação.
- Felipe definiu: uma transferência só conta para os dois agentes quando há pelo menos uma mensagem do agente de origem antes da transferência. Em `enforce`, o owner final conta uma vez por ciclo; o anterior só conta com prova outbound hidratada, ator mapeado para `hubspot_user_id` e mensagem dentro do período em que tinha o ticket. Sem prova, a atribuição por agente é conservadora. Histórico sem ciclo conserva a contagem legada; não houve backfill de mensagens.
- A migration `0035` aceita horário de atribuição/transferência desconhecido. Os schemas de API aceitam `NULL`; reverse do schema após gravações nulas não é rollback seguro.
- Nenhuma alteração de scopes, app publicada, banco remoto, deploy ou backfill foi executada.
