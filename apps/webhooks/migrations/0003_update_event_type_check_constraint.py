"""
Migration to update the webhook_events event_type check constraint.

The original constraint only allowed conversation.* events, but HubSpot
sends ticket.*, contact.*, deal.*, and company.* events as well.

This migration was already applied directly to the database via Supabase
on 2026-04-01. This file documents the change for version control.
"""

from django.db import migrations


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            ALTER TABLE webhook_events DROP CONSTRAINT IF EXISTS webhook_events_event_type_check;

            ALTER TABLE webhook_events ADD CONSTRAINT webhook_events_event_type_check CHECK (
                event_type = ANY (ARRAY[
                    -- Conversation events (existing)
                    'conversation.creation',
                    'conversation.deletion',
                    'conversation.privacyDeletion',
                    'conversation.propertyChange',
                    'conversation.newMessage',
                    -- Ticket events (HubSpot)
                    'ticket.creation',
                    'ticket.created',
                    'ticket.deletion',
                    'ticket.propertyChange',
                    'ticket.associationChange',
                    'ticket.restored',
                    'ticket.merged',
                    -- Contact events (HubSpot)
                    'contact.creation',
                    'contact.created',
                    'contact.deletion',
                    'contact.propertyChange',
                    'contact.associationChange',
                    'contact.restored',
                    'contact.merged',
                    -- Deal events (HubSpot)
                    'deal.creation',
                    'deal.deletion',
                    'deal.propertyChange',
                    'deal.associationChange',
                    -- Company events (HubSpot)
                    'company.creation',
                    'company.deletion',
                    'company.propertyChange',
                    'company.associationChange',
                    -- Generic/unknown fallback
                    'unknown'
                ])
            );
        """)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            ALTER TABLE webhook_events DROP CONSTRAINT IF EXISTS webhook_events_event_type_check;

            ALTER TABLE webhook_events ADD CONSTRAINT webhook_events_event_type_check CHECK (
                event_type = ANY (ARRAY[
                    'conversation.creation',
                    'conversation.deletion',
                    'conversation.privacyDeletion',
                    'conversation.propertyChange',
                    'conversation.newMessage'
                ])
            );
        """)


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0002_rename_webhook_events_type_processed_idx_webhook_eve_event_t_f5eefa_idx"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
