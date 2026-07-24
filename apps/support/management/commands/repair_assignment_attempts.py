"""Repair durable assignment attempts from an authoritative runtime."""

from django.core.management.base import BaseCommand

from apps.support.availability_runtime import require_routing_writer_authority
from apps.support.durable_assignment_service import repair_assignment_attempts


class Command(BaseCommand):
    """Converge a bounded batch of incomplete assignment attempts."""

    help = "Repair stale, ambiguous, retryable, or externally-applied attempts."

    def add_arguments(self, parser) -> None:
        """Register the bounded batch size."""
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options) -> None:
        """Run repair and print only aggregate, non-sensitive counts."""
        require_routing_writer_authority("repair_assignment_attempts_command")
        result = repair_assignment_attempts(limit=max(1, min(options["limit"], 1000)))
        self.stdout.write(self.style.SUCCESS(str(result)))
