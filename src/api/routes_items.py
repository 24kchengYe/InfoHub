"""Item CRUD routes."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger("infohub.api.items")
router = APIRouter(prefix="/api", tags=["items"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class ItemPatchBody(BaseModel):
    is_read: Optional[bool] = None
    is_starred: Optional[bool] = None


class BatchReadBody(BaseModel):
    ids: List[str]
    is_read: bool = True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/items")
async def list_items(
    request: Request,
    domain: Optional[str] = Query(None, description="Filter by domain"),
    category: Optional[str] = Query(None, description="Filter by category (model/product/industry/paper/tip)"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    min_score: Optional[float] = Query(None, description="Minimum score"),
    search: Optional[str] = Query(None, description="Full-text search"),
    is_read: Optional[bool] = Query(None, description="Filter read/unread"),
    days: Optional[int] = Query(None, description="Filter to last N days (e.g. 1, 3, 7)"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    sort: str = Query("date", description="Sort by: score | date"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """Paginated item listing with filters."""
    db = request.app.state.db
    try:
        sort_col = "ai_score" if sort in ("score", "ai_score") else "published_at"
        result = await db.get_items(
            domain=domain,
            source=source_type,
            min_score=min_score,
            search=search,
            is_read=is_read,
            days=days,
            date_from=date_from,
            date_to=date_to,
            sort=sort_col,
            page=page,
            per_page=per_page,
            category=category,
        )
        # Serialize ContentItem objects to dicts
        items = result["items"]
        serialized = [item.model_dump(mode="json") for item in items]
        return {
            "data": serialized,
            "meta": {"total": result["total"], "page": page, "per_page": per_page},
        }
    except Exception as exc:
        logger.error("list_items error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/items/{item_id}")
async def get_item(request: Request, item_id: str):
    """Single item detail."""
    db = request.app.state.db
    item = await db.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"data": item.model_dump(mode="json")}


@router.patch("/items/batch-read")
async def batch_read(request: Request, body: BatchReadBody):
    """Batch mark items as read/unread."""
    db = request.app.state.db
    try:
        await db.batch_update_items(body.ids, {"is_read": body.is_read})
        return {"data": {"updated": len(body.ids)}}
    except Exception as exc:
        logger.error("batch_read error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/items/{item_id}")
async def patch_item(request: Request, item_id: str, body: ItemPatchBody):
    """Update is_read / is_starred on a single item."""
    db = request.app.state.db

    item = await db.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        await db.update_item(item_id, updates)
        return {"data": {"id": item_id, **updates}}
    except Exception as exc:
        logger.error("patch_item error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
