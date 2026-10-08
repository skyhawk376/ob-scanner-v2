import hmac
import os
from contextlib import asynccontextmanager

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.api.main import app

TOKEN = os.environ.get("MCP_TOKEN", "").encode()

if TOKEN:
    from mcp.server.transport_security import TransportSecuritySettings
    from app.mcp.server import mcp

    HOSTS = os.environ.get("MCP_ALLOWED_HOSTS", "ob-scanner-v2.fly.dev").split(",")

    class BearerAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            header = request.headers.get("authorization", "").encode()
            if not hmac.compare_digest(header, b"Bearer " + TOKEN):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=HOSTS,
        allowed_origins=[f"https://{h}" for h in HOSTS],
    )
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", transport_security=security
    )
    mcp_app.add_middleware(BearerAuth)

    _orig_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _lifespan(a):
        async with _orig_lifespan(a):
            async with mcp.session_manager.run():
                yield

    app.router.lifespan_context = _lifespan
    app.mount("/", mcp_app)
