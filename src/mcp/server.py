"""InfoHub MCP Server — Claude Code tools for querying and controlling InfoHub.

Runs as a standalone stdio MCP server. Each tool function creates its
own Database connection (via the module-level helpers in database.py)
so there is no shared state across invocations.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Project paths — the MCP server is an independent process, so we use
# absolute imports anchored to the InfoHub src package.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path("D:/InfoHub")
DB_PATH = PROJECT_ROOT / "data" / "infohub.db"

# Ensure the src package is importable when this file is executed directly.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import (  # noqa: E402
    init_db,
    get_items,
    get_daily_summary,
    get_stats,
    upsert_items,
)
from src.config import load_global_config, load_domain_configs, load_domain_config  # noqa: E402
from src.pipeline import InfoHubPipeline  # noqa: E402

logger = logging.getLogger(__name__)

mcp = FastMCP(name="infohub")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_db() -> None:
    """Ensure the database schema exists."""
    await init_db(DB_PATH)


def _item_to_dict(item) -> dict:
    """Serialise a ContentItem to a JSON-safe dict."""
    return {
        "id": item.id,
        "title": item.title,
        "url": str(item.url),
        "source": item.source_type.value,
        "author": item.author,
        "score": item.ai_score,
        "summary": item.ai_summary,
        "reason": item.ai_reason,
        "tags": item.ai_tags,
        "domain": item.domain,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "is_read": item.is_read,
        "is_starred": item.is_starred,
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def infohub_query(
    domain: Optional[str] = None,
    min_score: float = 6.0,
    hours: int = 24,
    limit: int = 20,
    search: Optional[str] = None,
) -> dict:
    """Query recent high-scoring information items from InfoHub.

    Args:
        domain: Filter by domain slug (e.g. "ai", "finance"). None for all.
        min_score: Minimum AI importance score (0-10). Default 6.0.
        hours: Look back window in hours. Default 24.
        limit: Maximum number of items to return. Default 20.
        search: Optional keyword search in title / content.

    Returns:
        dict with status, count, and items list.
    """
    try:
        await _ensure_db()
        result = await get_items(
            domain=domain,
            min_score=min_score,
            search=search,
            per_page=limit,
            db_path=DB_PATH,
        )
        items = [_item_to_dict(i) for i in result["items"]]
        # Apply hours filter client-side (db query doesn't have a since param)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        items = [
            i for i in items
            if i["published_at"] and datetime.fromisoformat(i["published_at"]) >= cutoff
        ]
        return {"status": "ok", "count": len(items), "items": items}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def infohub_daily(
    date: Optional[str] = None,
    domain: Optional[str] = None,
    language: str = "zh",
) -> dict:
    """Get the daily summary for a specific date and domain.

    Args:
        date: Date string YYYY-MM-DD. Defaults to today (UTC).
        domain: Domain slug. Required — pass the slug of the domain you want.
        language: Summary language, "zh" or "en". Default "zh".

    Returns:
        dict with status and the markdown summary.
    """
    try:
        await _ensure_db()
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not domain:
            # Try to return summaries for all domains
            configs = load_domain_configs()
            summaries = {}
            for dc in configs:
                s = await get_daily_summary(date, dc.slug, language, db_path=DB_PATH)
                if s:
                    summaries[dc.slug] = s.get("markdown", "")
            if not summaries:
                return {"status": "ok", "message": f"No summaries found for {date}"}
            return {"status": "ok", "date": date, "summaries": summaries}

        summary = await get_daily_summary(date, domain, language, db_path=DB_PATH)
        if not summary:
            return {"status": "ok", "message": f"No summary for {domain} on {date} ({language})"}
        return {
            "status": "ok",
            "date": date,
            "domain": domain,
            "language": language,
            "markdown": summary.get("markdown", ""),
            "item_count": summary.get("item_count", 0),
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def infohub_run_pipeline(
    domain: str = "all",
    hours: int = 24,
) -> dict:
    """Trigger the InfoHub pipeline to fetch, score, and summarise content.

    Args:
        domain: Domain slug to run, or "all" to run every enabled domain.
        hours: Look-back window in hours. Default 24.

    Returns:
        dict with per-domain results.
    """
    try:
        await _ensure_db()
        global_config = load_global_config()
        pipeline = InfoHubPipeline(db_path=DB_PATH, global_config=global_config)

        if domain == "all":
            configs = load_domain_configs()
        else:
            dc = load_domain_config(domain)
            if not dc:
                return {"status": "error", "message": f"Domain '{domain}' not found"}
            configs = [dc]

        results = {}
        for dc in configs:
            if not dc.enabled:
                results[dc.slug] = {"status": "skipped", "reason": "disabled"}
                continue
            try:
                r = await pipeline.run(dc, hours=hours)
                results[dc.slug] = r
            except Exception as exc:
                results[dc.slug] = {"status": "error", "message": str(exc)}

        return {"status": "ok", "results": results}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def infohub_stats(
    domain: Optional[str] = None,
    days: int = 7,
) -> dict:
    """Get InfoHub aggregate statistics.

    Args:
        domain: Optional domain slug to filter by.
        days: Number of days to aggregate over. Default 7.

    Returns:
        dict with total, unread, starred, by_source, avg_score, pipeline_runs.
    """
    try:
        await _ensure_db()
        stats = await get_stats(domain=domain, days=days, db_path=DB_PATH)
        return {"status": "ok", "data": stats}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def infohub_domains() -> dict:
    """List all configured information domains.

    Returns:
        dict with status and list of domains (slug, name, icon, enabled).
    """
    try:
        configs = load_domain_configs()
        domains = [
            {
                "slug": dc.slug,
                "name": dc.name,
                "icon": dc.icon,
                "color": dc.color,
                "enabled": dc.enabled,
                "sort_order": dc.sort_order,
            }
            for dc in configs
        ]
        return {"status": "ok", "count": len(domains), "domains": domains}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def infohub_search(
    query: str,
    domain: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Search information items by keyword.

    Args:
        query: Search keyword (matched against title and content).
        domain: Optional domain slug to narrow results.
        limit: Maximum results. Default 10.

    Returns:
        dict with status, count, and matching items.
    """
    try:
        await _ensure_db()
        result = await get_items(
            domain=domain,
            search=query,
            per_page=limit,
            db_path=DB_PATH,
        )
        items = [_item_to_dict(i) for i in result["items"]]
        return {"status": "ok", "count": len(items), "items": items}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Run the MCP server over stdio."""
    import os
    # Remove ALL_PROXY to prevent socks5 issues; HTTP(S)_PROXY is sufficient
    os.environ.pop("ALL_PROXY", None)
    os.environ.pop("all_proxy", None)
    mcp.run()


if __name__ == "__main__":
    main()
