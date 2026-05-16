"""Daily summary routes."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger("infohub.api.daily")
router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("")
async def list_dailies(
    request: Request,
    limit: int = Query(0, ge=0),
):
    """Available daily summaries. Includes today if items exist."""
    db = request.app.state.db
    try:
        summaries = await db.get_daily_summaries(limit=limit)
        # Check if today is already in the list
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing_dates = {s.get("date", "")[:10] for s in summaries}
        if today not in existing_dates:
            # Check if today has any high-score items
            result = await db.get_items(min_score=7.0, per_page=1, date_from=today, date_to=today)
            if result.get("total", 0) > 0:
                summaries.insert(0, {"date": today, "domain": "all", "language": "zh", "item_count": result["total"]})
        return {
            "data": summaries,
            "meta": {"total": len(summaries)},
        }
    except Exception as exc:
        logger.error("list_dailies error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/latest")
async def latest_daily(
    request: Request,
    domain: Optional[str] = Query(None),
    language: str = Query("zh"),
):
    """Most recent daily summary."""
    db = request.app.state.db
    try:
        summaries = await db.get_daily_summaries(limit=1)
        if not summaries:
            raise HTTPException(status_code=404, detail="No daily summaries available")
        latest_date = summaries[0].get("date") or summaries[0].get("created_at", "")[:10]
        summary = await db.get_daily_summary(
            date=latest_date, domain=domain, language=language
        )
        if summary is None:
            raise HTTPException(status_code=404, detail="No daily summary found")
        return {"data": summary}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("latest_daily error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{date}")
async def get_daily(
    request: Request,
    date: str,
    domain: Optional[str] = Query(None),
    language: str = Query("zh"),
):
    """Daily summary for a specific date. Auto-generates if not found."""
    db = request.app.state.db
    try:
        summary = await db.get_daily_summary(
            date=date, domain=domain, language=language
        )
        if summary is None:
            # Auto-generate from current items for this date
            from ..ai.summarizer import DailySummarizer
            # Get total items for this date (all scores)
            all_result = await db.get_items(
                domain=domain or None,
                per_page=1,
                date_from=date,
                date_to=date,
            )
            total_for_day = all_result.get("total", 0)
            # Get all high-score items (no per_page limit for daily generation)
            from ..database import get_items as db_get_items
            result = await db_get_items(
                domain=domain or None,
                min_score=7.0,
                sort="ai_score",
                per_page=500,
                date_from=date,
                date_to=date,
                db_path=db.db_path,
            )
            items = result.get("items", [])
            if not items:
                raise HTTPException(
                    status_code=404, detail=f"No daily summary for {date}"
                )
            summarizer = DailySummarizer()
            markdown = await summarizer.generate_summary(items, date, total_for_day, language=language)
            target_domain = domain or "all"
            await db.save_daily_summary(date, target_domain, language, markdown, len(items))
            summary = await db.get_daily_summary(date=date, domain=target_domain, language=language)
            if summary is None:
                raise HTTPException(status_code=404, detail=f"No daily summary for {date}")
        return {"data": summary}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_daily error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
