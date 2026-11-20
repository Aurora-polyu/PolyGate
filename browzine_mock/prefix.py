"""Public path support for the ceAI+ gateway.

The gateway serves the app at https://apps.polylink.org/<username>/<app-name>/, strips that prefix
before forwarding, and sends it in X-Forwarded-Prefix. Setting ASGI root_path from it lets /docs
request the right /openapi.json. Routes are unchanged. Only the exact /<username>/<app-name> shape is
accepted; any other value is ignored, never trusted. (A single segment is refused on purpose: Starlette
strips root_path from the request path, so /journals would turn /journals/J03 into a 404.)
"""

import re

SEGMENT = r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}"
PREFIX = re.compile(rf"/{SEGMENT}/{SEGMENT}")


class ForwardedPrefixMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            for name, value in scope["headers"]:
                if name == b"x-forwarded-prefix":
                    prefix = value.decode("latin-1")
                    if PREFIX.fullmatch(prefix) and ".." not in prefix:
                        scope = {**scope, "root_path": prefix}
                    break
        await self.app(scope, receive, send)
