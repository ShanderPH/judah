# Relacionamentos entre Modelos

## Resumo

Visão dos principais relacionamentos entre entidades do JUDAH.

## Diagrama textual

```text
User (auth_user)
  │1
  │
  │*
AgentPerformance ── date
  │
  │*
Agent (support)
  │1
  │
  │*
AssignedConversation ── agent (FK, nullable)
ClosedConversation ──── agent (FK, nullable)
AssignmentLog ───────── agent (FK, nullable)
AgentDailyTimeLog ───── agent (FK)
ConversationReassignment ─ from_agent / to_agent (FK, nullable)

Ticket (support)
  │1
  │
  │1
NewConversation (hubspot_ticket_id)
AssignedConversation (hubspot_ticket_id)
ClosedConversation (hubspot_ticket_id)

Church (church)
  │*
  │
  │1
Plan ─────── Church.plan (FK)
Gateway ──── Church.gateway (FK)

Category (knowledge)
  │1
  │
  │*
Article ──── Article.category_hubspot_id (CharField, lógico)
  │1
  │
  │*
ArticleChunk ── ArticleChunk.article (FK, nullable)

AgentSession (ai_agents)
  │1
  │
  │*
AgentMemory ── AgentMemory.session (FK)
AgentTrace ─── AgentTrace.session (FK)

WebhookEvent (webhooks)
  │1
  │
  │1
DeadLetterQueue ── DeadLetterQueue.event (OneToOne FK)
```

## Observações

- `Ticket` e conversas (`NewConversation`, `AssignedConversation`, `ClosedConversation`) não têm FK explícita; o vínculo é por `hubspot_ticket_id` / `ticket_id`.
- `Agent` não tem FK para `User`, mas `User.hubspot_owner_id` pode ser correlacionado com `Agent.hubspot_owner_id`.
- `AgentPerformance.agent` aponta para `settings.AUTH_USER_MODEL`, enquanto `AssignedConversation.agent` aponta para `support.Agent`.
- `Article` e `Category` são vinculados logicamente por `category_hubspot_id`.

## Arquivos relacionados

- [`database/models.md`](./models.md)
- [`database/migrations.md`](./migrations.md)
