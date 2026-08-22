# JUDAH inbound seguro para n8n 2.33.3

## 1. Workflows criados e modificados

- Criado: `[INHPK] BOT | 00 - JUDAH Inbound Gateway`.
- Modificado: `[INHPK] BOT | 03 - Conversation Message Gateway`.
- Modificado de forma isolada: `[INHPK] BOT | 04 - Triage Menu Router`, apenas para corrigir a regex de normalização de whitespace.
- Preservados sem edição: WF-01 e WF-02.

Os exports modificados estão com `active: false` quando são gateways externos/internos alterados nesta entrega. Nenhum workflow foi importado, publicado ou ativado em uma instância n8n.

## 2. Endpoint e contrato HTTP

O path definitivo documentado é:

```text
POST /webhook/judah-bot-inbound
```

O Webhook usa `options.rawBody: true` e responde por nodes `Respond to Webhook`. Autenticação inválida sempre retorna `401` com o corpo genérico definido no contrato. Payload inválido retorna `422`. Falha transitória ou resultado inválido do WF-03 retorna `500`. Aceitação válida retorna `202` com `status`, `event_id` e `duplicate`.

O WF-00 somente aceita o resultado quando `status == accepted`, o `event_id` é igual ao header e `duplicate` é booleano.

## 3. Nodes adicionados, alterados e removidos

### WF-00

Adicionados Webhook raw-body, preflight de headers/timestamp, Crypto HMAC-SHA256, comparação de tamanho fixo sem retorno antecipado, parse/validação do contrato, Crypto SHA-256 da chave canônica, chamada síncrona ao WF-03 e respostas 202/401/422/500.

O preflight lê o binário raw em Base64, decodifica como UTF-8 e exige round-trip byte a byte antes de formar `timestamp + "." + rawBody`. O Crypto v2 calcula o HMAC usando a credencial; nenhum JSON é reserializado antes da validação.

### WF-03

- Input `transport` Object adicionado sem alterar `data`.
- `Normalize New Message Event` agora distingue explicitamente JUDAH `source=judah/schema_version=1.0` do envelope legado.
- A tabela antiga `bot_conversation_events` não é removida. A inbox nova é `bot_conversation_events_v2`.
- O padrão `rowNotExists -> insert -> concluído` foi substituído por leitura, decisão por status, claim `PROCESSING`, finalização `PROCESSED/IGNORED` e falha `FAILED_RETRYABLE`.
- Adicionado cursor versionado `bot_conversation_thread_cursor_v1` para detectar execução recente por thread e ordem `(occurred_at, message_id)`.
- Adicionados branches `Needs Thread Lookup?` e `Needs Message Lookup?`. Mensagem canônica hidratada não passa por `GET New Message`.
- `ticket_id=null` mantém `GET Conversation Thread` como fallback de associação. Canais ausentes continuam usando o estado persistido.
- Os terminais `NO_CONVERSATION_STATE`, `IDENTITY_REQUIRED` e `IDENTITY_CORRECTION_REQUIRED` finalizam como retryable/pending, nunca como `PROCESSED`.
- `REGISTER_STATE` e as chamadas internas existentes foram preservados.

Nenhum node do backend, Celery Beat ou dispatch WF-04 -> JUDAH foi criado.

### WF-04

Somente estas expressões foram corrigidas no node `Interpret Triage Selection`:

```javascript
.replace(/[^a-z0-9\s]/g, ' ')
.replace(/\s+/g, ' ')
```

Nenhum node foi removido.

## 4. Contrato da credencial HMAC

Criar manualmente no cofre do n8n uma credencial built-in do tipo `Crypto`, sugerida com o nome `JUDAH Inbound HMAC`, preenchendo exclusivamente `Hmac Secret`. Depois, selecionar essa credencial no node `Compute HMAC-SHA256` do WF-00.

O export não contém ID de credencial, secret, assinatura recebida persistida, variáveis de ambiente nem valor de exemplo do secret. O WF-00 desabilita persistência de dados de execução de sucesso/erro no nível do workflow; a política global da instância também deve ser revisada antes da ativação.

## 5. Configuração manual necessária

1. Importar WF-00, WF-03 e, opcionalmente, o WF-04 corrigido em staging, mantendo-os desativados.
2. Vincular a credencial Crypto ao node HMAC.
3. Reassociar o node `Call WF-03 PROCESS_NEW_MESSAGE` ao ID real do WF-03 caso o import gere um novo ID.
4. Conferir as credenciais HubSpot e IDs dos subworkflows já existentes no WF-03; não substituir automaticamente.
5. Criar/inspecionar as Data Tables versionadas pelo primeiro teste manual e confirmar tipos/colunas.
6. Configurar manualmente `N8N_BOT_INBOUND_URL` no JUDAH para a URL definitiva somente em uma fase autorizada.
7. Aplicar a migration `0008_n8nthreaddeliverylock` em staging e validar contenção PostgreSQL antes da ativação.

## 6. Testes executados

Comando:

```powershell
node .\tests\verify-workflows.mjs
```

Resultado: `26/26 checks passed`. O conjunto cobre os 22 cenários obrigatórios, `REGISTER_STATE`, integridade/importabilidade dos grafos, regex isolada e ausência de secrets nos exports.

Os testes são offline e usam somente dados sintéticos. Não houve chamada a HubSpot, banco remoto, n8n real ou JUDAH.

## 7. Resultados

- HMAC válida/inválida, prefixo, replay passado/futuro e headers foram exercitados.
- Divergências de `event_id`, idempotency key, thread e payload são rejeitadas.
- Primeira entrega, duplicate, retry, claim expirado e concorrência foram exercitados na máquina de estados.
- Webhook/reconciliation, `ticket_id=null`, fallback de canais e mensagem fora de ordem foram cobertos.
- O grafo prova que mensagem hidratada passa pelo branch que evita `GET New Message`.
- WF-01/WF-02 não foram alterados; o input e o caminho `REGISTER_STATE` continuam presentes.

## 8. Limitações e gate de produção

n8n Data Tables 2.33.3 continuam sem constraint UNIQUE por coluna ou compare-and-set documentado. A garantia de exclusão mútua foi, portanto, implementada no dispatcher JUDAH por um lease PostgreSQL único em `hubspot_thread_id`. O lease mantém paralelismo entre threads distintas, impede dois claims simultâneos da mesma thread e é liberado somente ao finalizar sucesso/falha; leases abandonados são recuperáveis após um prazo maior ou igual ao orçamento total de timeout HTTP.

O teste sequencial SQLite e o gate em PostgreSQL local descartável passaram; no gate concorrente, dois outboxes da mesma thread produziram exatamente um claim. A integração não deve ser ativada antes de aplicar e validar a migration em staging, inclusive RLS e permissões da role de runtime. Também permanecem pendentes, por requisito, as implementações de `NO_CONVERSATION_STATE`, `IDENTITY_REQUIRED` e `IDENTITY_CORRECTION_REQUIRED`.

A exposição do raw body em `binary.data.data` e a credencial Crypto v2 foram conferidas contra o código oficial do n8n 2.33.3, mas ainda precisam de smoke test na imagem self-hosted real, inclusive quando `binaryMode=separate`.

## 9. Rollback

1. Manter o caminho HubSpot atual ativo e não apontar o JUDAH para o WF-00 durante a validação.
2. Se o staging falhar, desativar/remover apenas o WF-00 importado e restaurar o export anterior do WF-03/WF-04.
3. Não apagar `bot_conversation_events`, `bot_conversation_events_v2` ou `bot_conversation_thread_cursor_v1`; retenha para auditoria até aprovação de limpeza separada.
4. Reverter a credencial/URL somente no cofre/configuração operacional, sem expor o secret.

## 10. Confirmação de limites da entrega

Não houve commit, push, deploy, import em n8n, ativação/publicação, mudança de Celery Beat, configuração de URL/secret, desativação do caminho HubSpot atual ou inclusão de secrets. O backend JUDAH recebeu somente o modelo/migration de lease, claim/finalização por thread e respectivos testes autorizados na fase seguinte.
