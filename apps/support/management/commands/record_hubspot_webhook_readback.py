"""Record a published HubSpot app readback after comparing it with desired state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.support.webhook_proof import invalidate_webhook_proof, record_published_configuration


class Command(BaseCommand):
    """Store durable, versioned evidence from published configuration exports."""

    help = "Compare published HubSpot app/webhook exports with the private desired contract"

    def add_arguments(self, parser: CommandParser) -> None:
        """Add paths to published HubSpot readback exports."""
        parser.add_argument("--published-webhooks", type=Path, required=True)
        parser.add_argument("--published-app", type=Path, required=True)

    def handle(self, *args: object, **options: object) -> None:
        """Validate both published exports and fail the release gate on drift."""
        published_webhooks = cast(Path, options["published_webhooks"])
        published_app = cast(Path, options["published_app"])
        try:
            webhooks = json.loads(published_webhooks.read_text(encoding="utf-8"))
            app = json.loads(published_app.read_text(encoding="utf-8"))
            if not isinstance(webhooks, dict) or not isinstance(app, dict):
                raise ValueError("Published configurations must be JSON objects")
        except OSError, ValueError, TypeError:
            # An unreadable export cannot leave a previous successful proof active.
            invalidate_webhook_proof()
            raise CommandError("Invalid HubSpot readback export") from None
        try:
            proof = record_published_configuration(webhooks, app)
        except OSError, ValueError, KeyError, TypeError, AttributeError:
            raise CommandError("Invalid HubSpot configuration or readback") from None
        self.stdout.write(json.dumps(proof, sort_keys=True))
        if not proof["ready"]:
            raise CommandError("Published HubSpot configuration differs from the private desired contract")
