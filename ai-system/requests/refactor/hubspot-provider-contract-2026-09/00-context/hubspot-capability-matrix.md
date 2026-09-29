# Matriz de capabilities HubSpot — gate operacional 2026-09-29

| Capability | Contrato | Scope | Token de produção | Prova |
|---|---|---|---|---|
| Tickets read | `/crm/objects/2026-09/tickets` | `crm.objects.tickets.read` e legado `tickets` | `available` | GET com token real |
| Tickets owner PATCH | `/crm/objects/2026-09/tickets/{id}` | `crm.objects.tickets.write` e legado `tickets` | `unverified` | Nenhum PATCH de produção; exige ticket de sandbox |
| Teams membership | `/settings/teams/2026-09/54655589/members` | `settings.users.teams.read` | `available` | GET e roster completo |
| Users identity/status | `/settings/users/2026-09/{userId}` | `settings.users.read` / `crm.objects.users.read` | `available` | GET e resolução do roster |
| Owners mapping | `/crm/owners/2026-09` | `crm.objects.owners.read` | `available` | GET e resolução do roster |
| Conversations | 2026-09 | scopes `conversations.read/write` preexistentes | `not_found` no probe opcional | Não bloqueia shadow |
| Journal | versão não comprovada | nenhum scope novo | `unverified` | Spike não adotado |

## Decisão de scopes

Build 20 publicado tinha `oauth`, `tickets`, `conversations.read`, `conversations.write`, `crm.objects.contacts.read`, `crm.objects.users.read`, `settings.users.read` e `settings.users.teams.read`. O manifesto versionado omitia os dois scopes de Conversations; foram restaurados para evitar remoção acidental.

Build 21 adicionou somente `crm.objects.tickets.read`, `crm.objects.tickets.write` e `crm.objects.owners.read`. `tickets` foi mantido. A [migração oficial de scopes](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/migrate-an-app/update-your-app-to-granular-scopes) mapeia `tickets` para quatro scopes, incluindo `crm.schemas.tickets.read/write`; duas capacidades de schema e chamadas legadas do JUDAH ainda não foram comprovadas sem `tickets`. Remoção exige inventário e teste isolado. O app não recebeu `automation`, `crm.pipelines.governance.write` nem `crm.pipelines.approval.read`.

O [catálogo oficial](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes) liga `crm.objects.owners.read` à leitura de Owners e os scopes granulares à leitura/escrita de Tickets. Os scopes de Conversations e o legado `tickets` são permissões anteriores preservadas, não ampliações desta publicação. O app é de token estático; a [documentação de instalação](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/manage-apps-in-hubspot) exige reinstall após mudar scopes.

Build 21 foi publicado no portal `47354717`, app UID `judah_hubspot_integration`, e reinstalado. `hs project app-install-status --json` retornou `isInstalledWithCurrentScopes=true`. Preflight com token real do serviço Railway confirmou portal `47354717`, time `54655589`, 7 membros ativos do tipo `DEFAULT`, paginação completa em uma página e zero owners ausentes. Sete é observação do provider, não constante de código.

Ver [evidência operacional](../03-verification/provider-contract-operational-gate.md) e [JSON do preflight](../03-verification/production-preflight.json).
