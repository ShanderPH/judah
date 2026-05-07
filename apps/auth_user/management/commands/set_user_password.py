"""Reset a user's password by username or email."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.auth_user.models import User


class Command(BaseCommand):
    help = "Set a user's password. Locate the user by --username or --email."

    def add_arguments(self, parser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--username", help="Login username")
        group.add_argument("--email", help="Registered email (case-insensitive)")
        parser.add_argument(
            "--password",
            required=True,
            help="New raw password to set",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Force is_active=True after the reset",
        )

    def handle(self, *args, **options) -> None:
        username = options.get("username")
        email = options.get("email")
        password: str = options["password"]

        if username:
            user = User.objects.filter(username=username).first()
            lookup = f"username={username!r}"
        else:
            user = User.objects.filter(email__iexact=email).first()
            lookup = f"email={email!r}"

        if user is None:
            raise CommandError(f"No user found for {lookup}.")

        user.set_password(password)
        if options.get("activate"):
            user.is_active = True
        user.save(update_fields=["password", "is_active", "updated_at"] if options.get("activate") else ["password", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Password updated for user id={user.pk} username={user.username!r} email={user.email!r}",
            ),
        )
