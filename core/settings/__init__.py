"""Settings loader — selects config based on DJANGO_ENV environment variable."""

import os

_env = os.environ.get("DJANGO_ENV", "development").lower()

if _env == "production":
    from .production import *
elif _env == "test":
    from .test import *
else:
    from .development import *
