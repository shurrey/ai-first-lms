"""Re-sends the auth cookies after sliding expiry extended the session.

Pure ASGI so streaming (SSE) responses pass through untouched. Responses that
already set `lms_session` (login, logout) are left alone.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from engine.auth.config import SESSION_COOKIE, AuthSettings
from engine.auth.cookies import auth_cookie_headers
from engine.auth.deps import COOKIE_REFRESH_STATE

_SESSION_PREFIX = f"{SESSION_COOKIE}=".encode()


class SessionCookieRefreshMiddleware:
    def __init__(self, app: ASGIApp, settings: AuthSettings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                refresh = scope.get("state", {}).get(COOKIE_REFRESH_STATE)
                headers = list(message.get("headers", []))
                already_set = any(
                    k == b"set-cookie" and v.startswith(_SESSION_PREFIX) for k, v in headers
                )
                if refresh is not None and not already_set:
                    token, csrf = refresh
                    headers.extend(
                        (b"set-cookie", v) for v in auth_cookie_headers(token, csrf, self.settings)
                    )
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
