"""Supabase client singleton for JUDAH."""

import structlog
from supabase import Client, create_client

logger = structlog.get_logger(__name__)

_supabase_client: Client | None = None


def get_supabase_client() -> Client:
    """Return the shared Supabase client instance (singleton).

    Reads SUPABASE_URL and SUPABASE_SERVICE_KEY from Django settings.

    Returns:
        A configured Supabase Client instance.
    """
    global _supabase_client
    if _supabase_client is None:
        from django.conf import settings

        url: str = settings.SUPABASE_URL
        key: str = settings.SUPABASE_SERVICE_KEY

        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")

        _supabase_client = create_client(url, key)
        logger.info("supabase_client_initialized", url=url)

    return _supabase_client
