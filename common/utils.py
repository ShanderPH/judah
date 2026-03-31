"""General-purpose utility functions for JUDAH."""

import re
import uuid
from datetime import datetime, timezone


def generate_uuid() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def truncate(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to a maximum length, appending suffix if truncated."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def chunk_list(lst: list, size: int) -> list[list]:
    """Split a list into chunks of a given size."""
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def mask_secret(value: str, visible_chars: int = 4) -> str:
    """Mask a secret string, showing only the last N characters."""
    if len(value) <= visible_chars:
        return "*" * len(value)
    return "*" * (len(value) - visible_chars) + value[-visible_chars:]


def is_valid_email(email: str) -> bool:
    """Validate an email address using a simple regex."""
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))
