"""Safely link an existing Judah user to a HubSpot support owner."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.support.models import Agent


class Command(BaseCommand):
    """Provision the two records required by Judah's support Matchmaker."""

    help = (
        "Link an existing Judah user to a HubSpot owner and create the "
        "corresponding support Agent. Runs as a dry-run unless --execute is supplied."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--username", required=True)
        parser.add_argument("--hubspot-owner-id", required=True, type=int)
        parser.add_argument(
            "--agent-email",
            default="",
            help="Agent email override. By default, uses the existing Judah user's email.",
        )
        parser.add_argument(
            "--agent-name",
            default="",
            help="Agent display name override. By default, uses full name or username.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Persist the validated provisioning plan.",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        username = str(options["username"]).strip()
        owner_id = int(options["hubspot_owner_id"])
        execute = bool(options["execute"])
        if owner_id <= 0:
            raise CommandError("--hubspot-owner-id must be a positive integer.")

        user_model = get_user_model()
        try:
            user = user_model.objects.select_for_update().get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"Judah user '{username}' does not exist.") from exc

        email = str(options["agent_email"] or user.email or "").strip().lower()
        if not email:
            raise CommandError(f"Judah user '{username}' has no email; provide --agent-email explicitly.")
        name = str(options["agent_name"] or user.get_full_name() or user.username).strip()

        current_user_owner = str(user.hubspot_owner_id or "").strip()
        if current_user_owner and current_user_owner != str(owner_id):
            raise CommandError(
                f"Judah user '{username}' is already linked to HubSpot owner "
                f"{current_user_owner}; refusing to overwrite it."
            )

        owner_matches = list(Agent.objects.select_for_update().filter(hubspot_owner_id=owner_id).order_by("created_at"))
        if len(owner_matches) > 1:
            raise CommandError(
                f"Found {len(owner_matches)} support agents with HubSpot owner {owner_id}; "
                "repair the duplicate data before provisioning."
            )
        owner_agent = owner_matches[0] if owner_matches else None
        email_agent = Agent.objects.select_for_update().filter(agent_email__iexact=email).order_by("created_at").first()

        if owner_agent is not None and owner_agent.agent_email.lower() != email:
            raise CommandError(f"HubSpot owner {owner_id} is already assigned to a different support-agent email.")
        if email_agent is not None and email_agent.hubspot_owner_id != owner_id:
            raise CommandError(
                f"Support-agent email '{email}' is already assigned to HubSpot owner {email_agent.hubspot_owner_id}."
            )

        agent_exists = owner_agent is not None
        self.stdout.write(
            self.style.WARNING("DRY-RUN provisioning plan" if not execute else "Executing provisioning plan")
        )
        self.stdout.write(f"Judah user: {username}")
        self.stdout.write(f"HubSpot owner: {owner_id}")
        self.stdout.write(f"Support agent: {name} <{email}>")
        self.stdout.write(f"Agent action: {'reuse existing' if agent_exists else 'create'}")
        self.stdout.write("User role: preserved")

        if not execute:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("No database changes were made."))
            return

        if current_user_owner != str(owner_id):
            user.hubspot_owner_id = str(owner_id)
            user.save(update_fields=["hubspot_owner_id", "updated_at"])

        if owner_agent is None:
            owner_agent = Agent.objects.create(
                name=name,
                agent_email=email,
                hubspot_owner_id=owner_id,
                status_enum=Agent.StatusEnum.OFFLINE,
                current_simultaneous_chats=0,
                max_simultaneous_chats=5,
                auto_assign_enabled=True,
                is_active=True,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Provisioned Judah user '{username}' and support agent {owner_agent.pk} for HubSpot owner {owner_id}."
            )
        )
