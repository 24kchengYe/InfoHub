"""Statistics routes."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger("infohub.api.stats")
router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
async def overview(
    request: Request,
    domain: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
):
    """Overview stats: total items, today count, unread count, per-domain counts."""
    db = request.app.state.db
    try:
        stats = await db.get_stats(domain=domain, days=days)
        return {"data": stats}
    except Exception as exc:
        logger.error("overview error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/daily-trend")
async def daily_trend(
    request: Request,
    domain: Optional[str] = Query(None),
    days: int = Query(14, ge=1, le=365),
):
    """Daily item counts for the past N days."""
    db = request.app.state.db
    try:
        data = await db.get_daily_trend(domain=domain, days=days)
        return {"data": data}
    except Exception as exc:
        logger.error("daily_trend error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/score-distribution")
async def score_distribution(
    request: Request,
    domain: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
):
    """Score distribution histogram."""
    db = request.app.state.db
    try:
        data = await db.get_score_distribution(domain=domain, days=days)
        return {"data": data}
    except Exception as exc:
        logger.error("score_distribution error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/sources")
async def sources(
    request: Request,
    domain: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
):
    """Per-source item counts."""
    db = request.app.state.db
    try:
        stats = await db.get_stats(domain=domain, days=days)
        # get_stats returns a dict that includes a "sources" key
        source_stats = stats.get("sources", [])
        return {
            "data": source_stats,
            "meta": {"total": len(source_stats)},
        }
    except Exception as exc:
        logger.error("sources error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/source-breakdown")
async def source_breakdown(
    request: Request,
    domain: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
):
    """Per-feed/source-name item counts (e.g. each RSS feed individually)."""
    db = request.app.state.db
    try:
        data = await db.get_source_breakdown(domain=domain, days=days)
        return {"data": data}
    except Exception as exc:
        logger.error("source_breakdown error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
