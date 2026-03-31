"""Settings loader — selects config based on DJANGO_ENV environment variable."""

import os

_env = os.environ.get("DJANGO_ENV", "development").lower()

if _env == "production":
    from .production import *  # noqa: F401, F403
elif _env == "test":
    from .test import *  # noqa: F401, F403
else:
    from .development import *  # noqa: F401, F403
