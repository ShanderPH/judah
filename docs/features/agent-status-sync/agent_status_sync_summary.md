# Agent Status Sync & Conversation Reassignment Tracking

## Overview

This feature addresses two critical issues in the agent assignment system:

1. **Conversation count accuracy**: The system now correctly tracks when tickets are reassigned between agents
2. **Pre-assignment status verification**: Before assigning a ticket, the system syncs all agents' status and conversation counts from HubSpot

## Changes Made

### 1. New Model: `ConversationReassignment`

**File**: `apps/support/models.py`

Tracks ticket transfers between agents with:
- `from_agent` / `to_agent`: Agent references
- `from_hubspot_owner_id` / `to_hubspot_owner_id`: HubSpot owner IDs
- `reassigned_at`: Timestamp of reassignment
- `time_with_previous_agent_seconds`: Duration ticket was with previous agent
- `reassignment_source`: Source of the reassignment event

**Table**: `conversation_reassignments`

### 2. Webhook Handler for Owner Changes

**File**: `apps/webhooks/handlers/hubspot_handler.py`

New function `_handle_ticket_owner_change()`:
- Triggered when `hubspot_owner_id` property changes on a ticket
- Decrements previous owner's `current_simultaneous_chats`
- Increments new owner's `current_simultaneous_chats`
- Updates `AssignedConversation` record with new owner
- Creates `ConversationReassignment` record for metrics

### 3. HubSpot Client: Active Ticket Count

**File**: `apps/integrations/hubspot/client.py`

New method `count_active_tickets_by_owner()`:
- Queries HubSpot Tickets Search API
- Counts non-closed tickets assigned to a specific owner
- Used to sync accurate conversation counts

### 4. Pre-Assignment Sync Function

**File**: `apps/support/auto_assign_service.py`

New function `sync_all_agents_status_and_counts()`:
- Fetches availability status for all users from HubSpot Users API
- Fetches active ticket counts in parallel (ThreadPoolExecutor, max 5 workers)
- Updates agent `status_enum` if changed
- Corrects `current_simultaneous_chats` if divergent from HubSpot
- Creates `AgentStatusHistory` records for status changes

### 5. Enhanced Assignment Flow

**File**: `apps/support/auto_assign_service.py`

Modified `attempt_auto_assign()`:
- Calls `sync_all_agents_status_and_counts()` before selecting agent
- Double-checks agent availability after sync
- Re-selects agent if originally selected agent is no longer available

### 6. Webhook Subscription

**File**: `hubspot-app/src/app/webhooks/judah-webhooks-hsmeta.json`

Added subscription for `ticket.propertyChange` on `hubspot_owner_id` property.

## Database Migration

**File**: `apps/support/migrations/0008_add_conversation_reassignment.py`

Creates the `conversation_reassignments` table with appropriate indexes.

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    TICKET REASSIGNMENT FLOW                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Agent A transfers ticket to Agent B in HubSpot                 │
│                          │                                       │
│                          ▼                                       │
│  HubSpot sends webhook: ticket.propertyChange                   │
│  propertyName: hubspot_owner_id                                 │
│  previousValue: Agent A's owner_id                              │
│  propertyValue: Agent B's owner_id                              │
│                          │                                       │
│                          ▼                                       │
│  _handle_ticket_owner_change()                                  │
│    ├── Decrement Agent A's current_simultaneous_chats           │
│    ├── Increment Agent B's current_simultaneous_chats           │
│    ├── Update AssignedConversation record                       │
│    └── Create ConversationReassignment record                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                  PRE-ASSIGNMENT SYNC FLOW                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  New ticket arrives → attempt_auto_assign()                     │
│                          │                                       │
│                          ▼                                       │
│  sync_all_agents_status_and_counts()                            │
│    ├── Fetch all users' availability (single API call)         │
│    ├── Fetch active ticket counts (parallel, 5 workers)        │
│    ├── Update agent status_enum if changed                      │
│    └── Correct current_simultaneous_chats if divergent          │
│                          │                                       │
│                          ▼                                       │
│  select_next_agent() with accurate data                         │
│                          │                                       │
│                          ▼                                       │
│  Double-check: agent.refresh_from_db()                          │
│  Verify agent.status_enum == ONLINE                             │
│                          │                                       │
│                          ▼                                       │
│  Assign ticket via HubSpot API                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Deployment Steps

1. Deploy the code changes
2. Run migration: `python manage.py migrate support`
3. Upload HubSpot app to register new webhook subscription:
   ```bash
   hs project upload
   ```

## Metrics Available

With `ConversationReassignment` records, you can now query:
- Number of reassignments per agent (from/to)
- Average time tickets spend with each agent before reassignment
- Tickets that required multiple reassignments
- Reassignment patterns and trends
