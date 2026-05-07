"""ASGI entry point for JUDAH — used by Uvicorn."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

_django_app = get_asgi_application()


async def application(scope, receive, send):
    """Wrap Django's ASGI app with a no-op lifespan handler.

    Django's get_asgi_application() implements the http + websocket scopes
    only; uvicorn warns "ASGI 'lifespan' protocol appears unsupported" on
    every boot. Handling lifespan ourselves silences the warning and lets
    us hook startup/shutdown probes if needed later.
    """
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    await _django_app(scope, receive, send)
