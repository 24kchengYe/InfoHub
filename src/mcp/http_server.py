"""InfoHub MCP Server — streamable HTTP entry point with bearer-token auth.

Run inside the infohub-mcp container:
    python -m src.mcp.http_server

Exposes the same FastMCP tools as the stdio server (src/mcp/server.py)
over streamable HTTP at http://0.0.0.0:18897/mcp so remote AI clients
(kimi-cli, Claude Code) can query the production InfoHub database.

Auth: static bearer token from the INFOHUB_MCP_TOKEN environment variable.
Requests without a matching `Authorization: Bearer <token>` header get 401.
"""

import logging
import os

import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from mcp.server.transport_security import TransportSecuritySettings

from src.mcp.server import mcp

logger = logging.getLogger(__name__)

# The MCP SDK rejects non-localhost Host headers by default (DNS-rebinding
# protection). Bearer auth already guards this endpoint, so allow the public
# host explicitly.
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["infohub.duqi.top", "infohub.duqi.top:*", "127.0.0.1:*", "localhost:*"],
    allowed_origins=["https://infohub.duqi.top", "http://127.0.0.1:*", "http://localhost:*"],
)

MCP_TOKEN = os.environ.get("INFOHUB_MCP_TOKEN", "")
HOST = os.environ.get("INFOHUB_MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("INFOHUB_MCP_PORT", "18897"))


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject any request without the correct bearer token."""

    async def dispatch(self, request, call_next):
        if not MCP_TOKEN:
            logger.error("INFOHUB_MCP_TOKEN is not set — refusing all requests")
            return JSONResponse({"error": "mcp token not configured"}, status_code=503)
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {MCP_TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def create_app():
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)
    return app


def main():
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    logger.info("InfoHub MCP (streamable HTTP) listening on %s:%d/mcp", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
