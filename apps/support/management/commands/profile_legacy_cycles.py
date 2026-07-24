"""Management command: profile_legacy_cycles

Read-only aggregate profile of legacy assignment data, produced to prepare
the conversation-cycle backfill (Gate E). The command:

- never creates, updates, deletes, closes, reopens, or reconciles any row;
- never calls the HubSpot API;
- exposes no PII — only whole-table aggregate counts;
- runs inside a transaction that is always rolled back, so even an
  accidental future write cannot persist.

Usage:
    python manage.py profile_legacy_cycles
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.support.legacy_cycle_profile import collect_legacy_cycle_profile


class Command(BaseCommand):
    help = "Print a deterministic, PII-free aggregate profile of legacy assignment data (read-only)."

    def handle(self, *args, **options):
        with transaction.atomic():
            profile = collect_legacy_cycle_profile()
            # Hard guarantee of read-only behavior: the surrounding atomic
            # block is always rolled back on exit, so nothing can be flushed.
            transaction.set_rollback(True)
        self.stdout.write(json.dumps(profile, indent=2, sort_keys=True))
