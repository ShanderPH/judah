"""Reset a user's password by username or email."""

from __future__ import annotations

import os
import sys

from django.core.management.base import BaseCommand, CommandError

from apps.auth_user.models import User


class Command(BaseCommand):
    help = "Set a user's password. Locate the user by --username or --email."

    def add_arguments(self, parser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--username", help="Login username")
        group.add_argument("--email", help="Registered email (case-insensitive)")

        secret = parser.add_mutually_exclusive_group(required=True)
        secret.add_argument("--password", help="New raw password (avoid for shells that expand metacharacters)")
        secret.add_argument(
            "--password-env",
            metavar="VARNAME",
            help="Name of the environment variable containing the new password",
        )
        secret.add_argument(
            "--password-stdin",
            action="store_true",
            help="Read the new password from stdin (single line, trailing newline trimmed)",
        )

        parser.add_argument(
            "--activate",
            action="store_true",
            help="Force is_active=True after the reset",
        )

    def _resolve_password(self, options: dict) -> str:
        if options.get("password"):
            return options["password"]
        if options.get("password_env"):
            var = options["password_env"]
            value = os.environ.get(var)
            if value is None:
                raise CommandError(f"Environment variable {var!r} is not set.")
            return value
        if options.get("password_stdin"):
            value = sys.stdin.readline()
            if not value:
                raise CommandError("No password received on stdin.")
            return value.rstrip("\r\n")
        raise CommandError("A password source is required.")

    def handle(self, *args, **options) -> None:
        username = options.get("username")
        email = options.get("email")
        password = self._resolve_password(options)

        if not password:
            raise CommandError("Password must not be empty.")

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
        user.save(
            update_fields=["password", "is_active", "updated_at"]
            if options.get("activate")
            else ["password", "updated_at"]
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Password updated for user id={user.pk} username={user.username!r} email={user.email!r}",
            ),
        )
