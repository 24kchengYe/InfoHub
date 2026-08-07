"""InfoHub MCP Server — streamable HTTP entry point with bearer-token auth.

Run inside the infohub-mcp container:
    python -m src.mcp.http_server

Exposes the same FastMCP tools as the stdio server (src/mcp/server.py)
over streamable HTTP at http://0.0.0.0:18897/mcp so remote AI clients
(kimi-cli, Claude Code) can query the production InfoHub database.

Auth: the primary bearer token comes from INFOHUB_MCP_TOKEN. Optional
per-client tokens can be supplied through INFOHUB_MCP_ADDITIONAL_TOKENS as a
comma-separated list, allowing individual credentials to be revoked without
sharing the owner token. Requests without a matching token get 401.
"""

import logging
import os
import hmac

import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from mcp.server.transport_security import TransportSecuritySettings

from src.mcp.server import mcp

logger = logging.getLogger(__name__)

# The MCP SDK rejects non-localhost Host headers by default (DNS-rebinding
# protection). Bearer auth already guards this endpoint, so allow the public
# host explicitly.
_extra_host = os.environ.get("INFOHUB_MCP_EXTRA_HOST", "")  # 如 Tailscale IP，经 env 注入不入库
_allowed_hosts = ["infohub.duqi.top", "infohub.duqi.top:*", "127.0.0.1:*", "localhost:*"]
if _extra_host:
    _allowed_hosts += [_extra_host, f"{_extra_host}:*"]
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_allowed_hosts,
    allowed_origins=["https://infohub.duqi.top", "http://127.0.0.1:*", "http://localhost:*"]
    + ([f"http://{_extra_host}:*"] if _extra_host else []),
)

MCP_TOKEN = os.environ.get("INFOHUB_MCP_TOKEN", "").strip()
MCP_ADDITIONAL_TOKENS = tuple(
    token.strip()
    for token in os.environ.get("INFOHUB_MCP_ADDITIONAL_TOKENS", "").split(",")
    if token.strip()
)
HOST = os.environ.get("INFOHUB_MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("INFOHUB_MCP_PORT", "18897"))


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject any request without the correct bearer token."""

    async def dispatch(self, request, call_next):
        if not MCP_TOKEN:
            logger.error("INFOHUB_MCP_TOKEN is not set — refusing all requests")
            return JSONResponse({"error": "mcp token not configured"}, status_code=503)
        auth = request.headers.get("authorization", "")
        supplied = auth[7:] if auth.startswith("Bearer ") else ""
        accepted = (MCP_TOKEN, *MCP_ADDITIONAL_TOKENS)
        if not supplied or not any(hmac.compare_digest(supplied, token) for token in accepted):
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
