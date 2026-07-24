"""Settings loader — selects config based on DJANGO_ENV environment variable."""

import os

_env = os.environ.get("DJANGO_ENV", "development").strip().lower()

if _env == "production":
    from .production import *
elif _env == "staging":
    from .staging import *
elif _env == "test":
    from .test import *
elif _env == "development":
    from .development import *
else:
    supported = "development, staging, production, test"
    raise RuntimeError(f"Unsupported DJANGO_ENV={_env!r}. Expected one of: {supported}.")
