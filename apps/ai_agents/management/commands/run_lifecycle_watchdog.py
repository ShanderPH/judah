"""Run the AI/helpdesk lifecycle watchdog."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ai_agents.services.watchdog import run_lifecycle_watchdog


class Command(BaseCommand):
    help = "Detect stuck conversation lifecycle instances and mark them for retry or terminal failure."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--max-failures", type=int, default=3)

    def handle(self, *args, **options) -> None:
        result = run_lifecycle_watchdog(
            limit=options["limit"],
            max_failures=options["max_failures"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Lifecycle watchdog complete: "
                f"scanned={result.scanned}, "
                f"retryable={result.marked_retryable}, "
                f"terminal={result.marked_terminal}"
            )
        )
