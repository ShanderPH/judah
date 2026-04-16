"""Management command: sync_novo_conversations

Syncs uninstanced conversations from HubSpot's NOVO stage into the internal
queue and optionally triggers automatic assignment.

This command is designed to be:
  - Run manually whenever needed (``python manage.py sync_novo_conversations``)
  - Called automatically on Celery worker startup via the ``worker_ready`` signal

Usage:
    python manage.py sync_novo_conversations
    python manage.py sync_novo_conversations --assign
    python manage.py sync_novo_conversations --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Sync HubSpot NOVO-stage tickets into the internal queue and optionally trigger auto-assignment."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assign",
            action="store_true",
            default=False,
            help="After syncing, trigger auto-assignment for any new tickets.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be synced without making changes.",
        )

    def handle(self, *args, **options):
        self.stdout.write(f"\n{'JUDAH — SYNC NOVO CONVERSATIONS':^60}")
        self.stdout.write(f"{timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z'):^60}\n")

        if options["dry_run"]:
            self._dry_run()
            return

        from apps.support.auto_assign_service import sync_novo_stage_tickets

        self.stdout.write("Fetching tickets in NOVO stage from HubSpot...")
        result = sync_novo_stage_tickets()

        if result.get("error"):
            self.stderr.write(f"  [ERR] HubSpot fetch failed: {result['error']}")
            return

        self.stdout.write(f"  Total from HubSpot: {result['total_from_hubspot']}")
        self.stdout.write(f"  Created (new):      {result['created']}")
        self.stdout.write(f"  Skipped (existing): {result['skipped']}")

        if result["created"] > 0:
            self.stdout.write(self.style.SUCCESS(f"\n  {result['created']} conversation(s) instanced and queued."))
        else:
            self.stdout.write("\n  No new conversations to instance.")

        # Show current queue state
        from apps.support.models import NewConversation

        pending = NewConversation.objects.count()
        self.stdout.write(f"\n  Queue depth: {pending} ticket(s) pending assignment")

        if options["assign"] and pending > 0:
            self.stdout.write("\nTriggering auto-assignment...")
            from apps.support.auto_assign_service import assign_pending_tickets

            assign_result = assign_pending_tickets()
            self.stdout.write(f"  Assigned: {assign_result['assigned']}")
            self.stdout.write(f"  Skipped:  {assign_result['skipped']}")

    def _dry_run(self):
        from apps.integrations.hubspot.client import get_hubspot_client
        from apps.support.models import AssignedConversation, NewConversation

        self.stdout.write("[DRY RUN] Checking HubSpot for NOVO-stage tickets...\n")

        client = get_hubspot_client()
        tickets = client.search_tickets_in_novo_stage()

        self.stdout.write(f"  Found {len(tickets)} ticket(s) in NOVO stage\n")

        would_create = 0
        would_skip = 0

        for ticket in tickets:
            ticket_id = str(ticket["id"])
            owner_id = ticket.get("owner_id", "")
            has_owner = owner_id and str(owner_id).strip() not in ("", "None", "null")

            in_new = NewConversation.objects.filter(hubspot_ticket_id=ticket_id).exists()
            in_assigned = AssignedConversation.objects.filter(hubspot_ticket_id=ticket_id).exists()

            if has_owner:
                self.stdout.write(f"  SKIP {ticket_id} — already has owner ({owner_id})")
                would_skip += 1
            elif in_new:
                self.stdout.write(f"  SKIP {ticket_id} — already in new_conversations")
                would_skip += 1
            elif in_assigned:
                self.stdout.write(f"  SKIP {ticket_id} — already in assigned_conversations")
                would_skip += 1
            else:
                subject = ticket.get("subject", "")[:50]
                self.stdout.write(f"  NEW  {ticket_id} — would queue: {subject}")
                would_create += 1

        self.stdout.write(f"\n  Would create: {would_create}")
        self.stdout.write(f"  Would skip:   {would_skip}")
