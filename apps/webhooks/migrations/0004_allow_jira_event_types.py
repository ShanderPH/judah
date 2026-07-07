"""Allow Jira webhook event types in the webhook_events constraint."""

from django.db import migrations


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            ALTER TABLE webhook_events DROP CONSTRAINT IF EXISTS webhook_events_event_type_check;

            ALTER TABLE webhook_events ADD CONSTRAINT webhook_events_event_type_check CHECK (
                event_type = ANY (ARRAY[
                    -- Conversation events (HubSpot)
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
                    -- Issue events (Jira)
                    'jira:issue_created',
                    'jira:issue_updated',
                    'jira:issue_deleted',
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


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0003_update_event_type_check_constraint"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
