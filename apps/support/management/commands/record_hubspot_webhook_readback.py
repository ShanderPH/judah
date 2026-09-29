"""Record a published HubSpot app readback after comparing it with desired state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.integrations.hubspot.webhook_config import compare_app_config, compare_webhook_config
from apps.support.provider_readiness import WEBHOOK_CONFIG_CACHE_KEY


class Command(BaseCommand):
    """Store a bounded readiness proof from externally obtained published JSON."""

    help = "Compare published HubSpot app/webhook readback exports with versioned manifests"

    def add_arguments(self, parser: CommandParser) -> None:
        """Add paths to published HubSpot readback exports.

        Args:
            parser: Django command argument parser.
        """
        parser.add_argument("--published-webhooks", type=Path, required=True)
        parser.add_argument("--published-app", type=Path, required=True)

    def handle(self, *args: object, **options: object) -> None:
        """Compare published exports and cache readiness.

        Args:
            *args: Positional command arguments.
            **options: Parsed command options.
        """
        desired_webhooks = settings.BASE_DIR / "hubspot-app/src/app/webhooks/judah-webhooks-hsmeta.json"
        desired_app = settings.BASE_DIR / "hubspot-app/src/app/app-hsmeta.json"
        published_webhooks = cast(Path, options["published_webhooks"])
        published_app = cast(Path, options["published_app"])
        try:
            webhook_result = compare_webhook_config(
                json.loads(desired_webhooks.read_text(encoding="utf-8")),
                json.loads(published_webhooks.read_text(encoding="utf-8")),
            )
            app_result = compare_app_config(
                json.loads(desired_app.read_text(encoding="utf-8")),
                json.loads(published_app.read_text(encoding="utf-8")),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError("Invalid HubSpot readback export") from exc
        ready = bool(webhook_result["ready"] and app_result["ready"])
        cache.set(
            WEBHOOK_CONFIG_CACHE_KEY,
            {"checked_at": timezone.now().isoformat(), "ready": ready},
            timeout=86400,
        )
        self.stdout.write(json.dumps({"webhooks": webhook_result, "app": app_result, "ready": ready}, sort_keys=True))
        if not ready:
            raise CommandError("Published HubSpot configuration differs from the versioned manifests")
