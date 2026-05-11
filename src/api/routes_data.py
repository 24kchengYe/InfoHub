"""Data management routes."""

import logging
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("infohub.api.data")
router = APIRouter(prefix="/api/data", tags=["data"])


@router.delete("/clear")
async def clear_all_data(request: Request):
    """Delete all items, pipeline runs, and daily summaries."""
    db = request.app.state.db
    try:
        await db.clear_all_data()
        return {"data": {"message": "All data cleared"}}
    except Exception as exc:
        logger.error("clear_all_data error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
