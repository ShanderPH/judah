# Resultado final do hotfix e integração #134

## Versões e isolamento

- Branch: hotfix/hubspot-webhook-proof-durability.
- Worktree: /tmp/judah-webhook-proof. Workspace original e alterações do usuário preservados.
- main sincronizada: 0ca25b842ef55607af210419a8c17c4b56d6074f.
- PR #134 confirmado duas vezes: 952ca9fd6639a4f66f7782ea9af20c4b6bbb80f3.
- Commit isolado do hotfix: 3c3492976d7a0335f0bd9a6093f521e2c53f4b55.
- Integração #134: 59304ef326509079f858583d7d6e5a1a18c7d907, merge somente na branch do hotfix, sem conflitos.
- Código/testes finais verificados: 433106fa74e1bf3672fe5f9902fea205ba65a76a.
- Árvore apps/support validada: f85e026e5af4056e56ebb2b7bdad669abb442f12. O último commit de evidências não modifica essa árvore, webapp nem configuração de deploy.

A base main permite testar o hotfix sem #134 antes da integração; evita atribuir recuperação de lifecycle ao fix do proof. #134 entrou por merge, preservando seu histórico e seus arquivos intactos (git diff entre seu HEAD e a branch nos cinco arquivos de código/testes/package é vazio).

## Causa raiz e resultado

A evidência publicada usava timeout=86400 e também era rejeitada por age>86400. Não havia renovação autoritativa runtime; a passagem do tempo removia a chave e tornava may_assign False. Callers registravam indevidamente runtime_authority_rejected mesmo em production/production.

Antes: proof true mais velho que 24h bloqueava, ou sumia do Redis. Depois: true, schema/fingerprint compatíveis e data válida continuam autorizando por qualquer idade; >24h aparece stale, age e warning. Ausência, ready diferente de True, legacy, schema desconhecido e mismatch continuam fail-closed. Capabilities, roster, capacity, absence/canary e runtime authority não foram relaxados.

## Persistência e fingerprint

Redis, mesma chave `hubspot_webhook_config_readback`, timeout=None. Sem migration, componente produtivo novo ou timer de renovação. TTL=-1 confirmado em Redis real. Isso é durabilidade contra expiração, não garantia contra flush/eviction/perda de persistência.

```json
{
  "schema_version": 1,
  "checked_at": "<instante real da comparação em ISO-8601>",
  "ready": true,
  "config_fingerprint": "02ddf88d19d02760de481329717482e6a118dfadb46a7c3c6effb22e2d0a1069"
}
```

SHA-256 do UTF-8 de `json.dumps({"app": app_manifest, "webhooks": webhook_manifest}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`. Inclui ambos os documentos desejados completos; ordem de chave/whitespace de JSON é ignorada, ordem de arrays é conservadoramente relevante. Fingerprint é derivado da versão em execução, sem copiar hash de outro deployment.

O comando só escreve ready=True depois de compare_webhook_config e compare_app_config retornarem ready=True. Drift escreve ready=False e falha o comando; exports malformados também substituem prova anterior por snapshot negativo. Nenhuma leitura runtime reescreve checked_at.

## Observabilidade determinística

`assignment_gate_rejected` pode retornar:

- auto_assignment_disabled
- canonical_capacity_writer_inactive
- provider_capabilities_unavailable
- provider_roster_stale
- provider_webhook_proof_missing
- provider_webhook_proof_invalid
- provider_webhook_proof_fingerprint_mismatch
- provider_evidence_unavailable
- invalid_canary_configuration
- absence_safe_not_enforced

`runtime_authority_rejected` vem exclusivamente da rejeição real de runtime em may_assign. Callers matchmaker e attempt_auto_assign não emitem mais esse evento para gates de provider.

Readiness diferencia hubspot_webhook_config_missing, hubspot_webhook_config_invalid e hubspot_webhook_config_fingerprint_mismatch. Legacy tem status fingerprint_missing e motivo invalid. Proof válido velho tem webhook_config_verified=True, webhook_config_stale=True, age_seconds e warnings=[hubspot_webhook_config_stale], com evento hubspot_webhook_proof_stale; não acrescenta blocker do assignment.

## Testes

`apps/support/tests/test_webhook_proof.py`: 39 casos coletados, incluindo o Redis opt-in. Cobre recente, limite 24h, 25h e 100 dias; warning/age/stale e ausência de renovação cega; ausente, false, legacy, fingerprint, schema, timestamp e ready malformados; hash dos dois manifests; persistência após o relógio do cache avançar 86401s e TTL real -1; comando falhando quando qualquer export diverge; negativo em export malformado; evento correto em production/production e staging; preservação da fila; assignment completo em capacity/provider/absence enforce com proof recente/antigo; demais gates; e recuperação de entrada #134 com proof ausente/stale sem bypass.

As assertions antigas e os testes de #134 ficaram intactos. Os 12 testes de recovery de #134 passaram. Scanner continua limitado a 100 e mantém retry/age budget; seus blockers de lifecycle não entraram no gate quente de provider.

## Gates

| Gate | Resultado |
|---|---|
| Python 3.14.7 isolado, SQLite | 1.040 passed, 51 skipped; coverage 90,85% |
| PostgreSQL 16 direcionado isolado | 104 passed |
| Python completo conjunto, SQLite | 1.054 passed, 51 skipped; coverage 90,91% |
| Python completo conjunto, PostgreSQL | 1.097 passed, 8 skipped; coverage 91,12% |
| Direcionados provider/assignment/SAT/cohort/lifecycle/protocol | 158 passed, 7 skipped em SQLite |
| Redis proof real (opt-in separado) | 1 passed; snapshot relido, TTL=-1, própria chave removida |
| Redis locks + Celery real + capacity retry (opt-in separado) | 6 passed, PostgreSQL local e Redis exclusivo 6388 |
| Ruff | clean |
| Ruff format | 386 arquivos clean |
| mypy | 383 arquivos clean |
| Django checks (SQLite e PostgreSQL) | zero issues |
| Migration drift (SQLite e PostgreSQL) | No changes detected |
| Migrations PostgreSQL local | aplicadas com sucesso |
| Pre-commit aplicável a hotfix + #134 | todos os hooks passaram |
| Webapp npm ci | passed, lockfile de #134 |
| Webapp lint | zero erros, um warning anterior use-api-query.ts:62 |
| Webapp typecheck | passed |
| Webapp Vitest | 11 arquivos, 66 testes passed |
| Webapp build padrão Turbopack | passed em container Node 24 descartável, sem rede |
| Webapp build Webpack adicional | passed no host |
| npm audit --omit=dev --audit-level=high | zero vulnerabilities |
| git diff --check | clean |

Os oito skips da suite PostgreSQL são sete opt-ins depois executados (proof Redis:1, owned locks:3, capacity Celery:1, Celery assignment:2), mais o teste exclusivo SQLite. Não ficou gate de Redis/Celery sem execução. Os skips SQLite incluem testes que exigem PostgreSQL, cobertos pela suite PostgreSQL.

Pre-commit all-files detectou whitespace anterior em install.cmd e cinco SVGs; correções automáticas desses arquivos foram desfeitas no worktree e não entraram no hotfix. Hooks aplicáveis ao diff e hooks nos commits passaram. Não alegar que o baseline all-files é clean.

## Limitações do ambiente resolvidas

- Primeira base local não correspondia à regex do trigger: corrigida para judah_ci_20261002_1, sem alterar guard/assertions.
- Turbopack no host restrito falhou ao bind de porta no processamento CSS. Build padrão repetido com a mesma árvore/dependências em Node 24 container (image digest sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6), sem rede: compiled successfully e 16 páginas geradas. Não houve mudança do script de build.
- Audit sob sandbox teve EAI_AGAIN; consulta fora do sandbox com cache/log em /tmp passou.

## Release e riscos

Ver ../05-deployment/release.md. Substituir o writer inline antigo por record_hubspot_webhook_readback alimentado por exports publicados atuais, antes de liberar nova versão. A primeira versão exige readback novo; não fabricar fingerprint para proof legado. Manter todas as validações pre-deploy existentes.

Redis pode perder a chave por outras causas; ausência permanece bloqueante. Não foi implementado monitoramento periódico autoritativo de drift publicado. Mudanças externas posteriores ao readback não são detectadas automaticamente; idade/warning tornam essa limitação visível. Falha de validação no pre-deploy grava evidência negativa na chave compartilhada e pode bloquear runtimes ativos; isso exige release controlado e exports autoritativos, sem escritores legados concorrentes. Nenhuma alteração de Railway ou configuração publicada foi feita aqui.

## Confirmação de limites

Nenhum merge em main, push, deploy Railway, variável externa alterada, mutation produtiva, Redis produtivo escrito, replay, repair histórico, backfill, PATCH HubSpot, mensagem, ticket real ou configuração HubSpot publicada foi executado. Apenas bases e Redis locais descartáveis foram escritos por testes. Redis exclusivo de Celery encerrado ao terminar; o container de build foi removido automaticamente.
