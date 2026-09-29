# Matriz de capabilities HubSpot — estado local

| Capability | Contrato usado | Obrigatória | Prova local | Prova da conta |
|---|---|---|---|---|
| Tickets read | `/crm/objects/2026-09/tickets` | sim | adapter/preflight testados | pendente sandbox |
| Tickets owner PATCH | `/crm/objects/2026-09/tickets/{id}` | sim | payload e erro testados; GET não prova escrita | pendente mutation sandbox autorizada |
| Teams membership | `/settings/teams/2026-09/{teamId}/members` | sim | paginação 0/1/100/101 e cursor | pendente sandbox |
| Users identity/status | `/settings/users/2026-09/{userId}` | sim | parsing e erro tipado | pendente sandbox |
| Owners mapping | `/crm/owners/2026-09` | sim | paginação e ligação `userId`→owner ID | pendente sandbox; manifesto não declara scope específico de Owners |
| Conversations | 2026-09 | não | registry apenas | spike `not adopted` |
| Journal | versão não comprovada | não | registry apenas | spike `not adopted` |

O [changelog 2026.09](https://developers.hubspot.com/changelog/fall-2026-spotlight) lista Tickets e Owners entre as APIs atualizadas. A [Teams API](https://developers.hubspot.com/docs/api-reference/latest/account/settings/teams/guide) documenta membership e `after`; a [Owners API](https://developers.hubspot.com/docs/api-reference/latest/crm/owners/guide) distingue `userId` de `id` de owner. A existência do endpoint documentado não comprova o acesso do app do JUDAH.

O manifesto local declara `oauth`, `tickets`, `crm.objects.contacts.read`, `crm.objects.users.read`, `settings.users.read` e `settings.users.teams.read`. Nenhum scope foi adicionado automaticamente. O preflight classifica 401/403; a lista efetiva de scopes e o menor ajuste necessário dependem do readback da conta/sandbox.
