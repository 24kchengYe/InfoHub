"""Pipeline trigger / status / cancel routes."""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger("infohub.api.pipeline")
router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

_current_run: dict | None = None
_cancel_event: asyncio.Event | None = None


class PipelineRunBody(BaseModel):
    domain: str = "all"
    hours: int = 0  # 0 = auto-detect from last fetch


async def _get_auto_hours(db_path) -> int:
    """Calculate hours since the last fetched item.

    Returns the number of hours to look back, capped at 168 (7 days).
    Falls back to 24 if the database is empty or on error.
    """
    try:
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute("SELECT MAX(fetched_at) FROM items")
            row = await cursor.fetchone()
            if row and row[0]:
                last_fetch = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                delta_hours = (now - last_fetch).total_seconds() / 3600
                hours = max(1, int(delta_hours) + 1)  # at least 1h, round up
                return min(hours, 168)  # cap at 7 days
    except Exception as exc:
        logger.warning("Auto-hours detection failed, defaulting to 24h: %s", exc)
    return 24


async def _run_pipeline_bg(config, db_path, domain: str, hours: int, run_id: str):
    """Execute the pipeline in the background with live progress updates."""
    global _current_run, _cancel_event

    # Auto-detect hours if not specified
    if hours <= 0:
        hours = await _get_auto_hours(db_path)
        logger.info("[Pipeline] Auto-detected hours=%d from last fetch", hours)

    _cancel_event = asyncio.Event()

    _current_run = {
        "run_id": run_id,
        "domain": domain,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        "phase": "starting",
        "current_domain": None,
        "domains_total": 0,
        "domains_done": 0,
        "fetched": 0,
        "scored": 0,
        "filtered": 0,
        # Detailed progress fields
        "sources_total": 0,
        "sources_done": 0,
        "current_source": "",
        "score_current": 0,
        "score_total": 0,
        "enrich_current": 0,
        "enrich_total": 0,
    }

    os.environ.pop("ALL_PROXY", None)
    os.environ.pop("all_proxy", None)

    try:
        from src.pipeline import InfoHubPipeline, PipelineCancelled
        from src.config import load_domain_configs, load_domain_config

        pipeline = InfoHubPipeline(db_path=db_path, global_config=config)

        if domain == "all":
            configs = load_domain_configs()
        else:
            dc = load_domain_config(domain)
            if not dc:
                _current_run["status"] = "error"
                _current_run["error"] = f"Domain '{domain}' not found"
                return
            configs = [dc]

        enabled = [dc for dc in configs if dc.enabled]
        _current_run["domains_total"] = len(enabled)

        results = {}
        total_fetched = 0
        total_scored = 0
        total_filtered = 0

        for idx, dc in enumerate(enabled):
            _current_run["current_domain"] = dc.name
            _current_run["domains_done"] = idx
            _current_run["phase"] = "fetching"
            # Reset per-domain detailed counters
            _current_run["sources_done"] = 0
            _current_run["sources_total"] = 0
            _current_run["current_source"] = ""
            _current_run["score_current"] = 0
            _current_run["score_total"] = 0
            _current_run["enrich_current"] = 0
            _current_run["enrich_total"] = 0

            try:
                def on_progress(phase: str, detail):
                    nonlocal total_fetched, total_scored, total_filtered

                    if phase == "fetch_source":
                        # detail: {"source": str, "index": int, "total": int, "fetched_so_far": int}
                        _current_run["current_source"] = detail["source"]
                        _current_run["sources_done"] = detail["index"] - 1
                        _current_run["sources_total"] = detail["total"]
                        _current_run["phase"] = "fetching"
                        _current_run["fetched"] = detail.get("fetched_so_far", _current_run.get("fetched", 0))

                    elif phase == "fetch_source_done":
                        # detail: {"source": str, "index": int, "total": int, "source_count": int, "fetched_so_far": int}
                        _current_run["sources_done"] = detail["index"]
                        _current_run["fetched"] = detail["fetched_so_far"]
                        _current_run["last_source_count"] = detail["source_count"]

                    elif phase == "fetch_done":
                        # detail: {"count": int}
                        count = detail["count"]
                        total_fetched = _current_run.get("fetched", 0) + count - _current_run.get("_last_fetched", 0)
                        _current_run["fetched"] = total_fetched
                        _current_run["_last_fetched"] = count
                        _current_run["sources_done"] = _current_run["sources_total"]
                        _current_run["current_source"] = ""
                        _current_run["phase"] = "scoring"

                    elif phase == "score_item":
                        # detail: {"index": int, "total": int}
                        _current_run["score_current"] = detail["index"]
                        _current_run["score_total"] = detail["total"]
                        _current_run["phase"] = "scoring"

                    elif phase == "score_done":
                        # detail: {"count": int}
                        count = detail["count"]
                        total_scored = _current_run.get("scored", 0) + count - _current_run.get("_last_scored", 0)
                        _current_run["scored"] = total_scored
                        _current_run["_last_scored"] = count
                        _current_run["phase"] = "filtering"

                    elif phase == "filter_done":
                        # detail: {"count": int}
                        count = detail["count"]
                        total_filtered = _current_run.get("filtered", 0) + count - _current_run.get("_last_filtered", 0)
                        _current_run["filtered"] = total_filtered
                        _current_run["_last_filtered"] = count
                        _current_run["phase"] = "enriching"

                    elif phase == "enrich_item":
                        # detail: {"index": int, "total": int}
                        _current_run["enrich_current"] = detail["index"]
                        _current_run["enrich_total"] = detail["total"]
                        _current_run["phase"] = "enriching"

                # Reset per-domain internal counters
                _current_run["_last_fetched"] = 0
                _current_run["_last_scored"] = 0
                _current_run["_last_filtered"] = 0

                r = await pipeline.run(
                    dc, hours=hours,
                    on_progress=on_progress,
                    cancel_event=_cancel_event,
                )
                results[dc.slug] = r

            except PipelineCancelled:
                results[dc.slug] = {"status": "cancelled"}
                _current_run["status"] = "cancelled"
                _current_run["phase"] = "cancelled"
                _current_run["finished_at"] = datetime.now(timezone.utc).isoformat()
                _current_run["results"] = results
                logger.info("Pipeline cancelled by user for domain %s", dc.slug)
                # Stop processing further domains
                break

            except Exception as exc:
                results[dc.slug] = {"status": "error", "message": str(exc)}
                logger.error("Pipeline %s failed: %s", dc.slug, exc, exc_info=True)

        if _current_run["status"] != "cancelled":
            _current_run["domains_done"] = len(enabled)
            _current_run["status"] = "completed"
            _current_run["phase"] = "done"
            _current_run["finished_at"] = datetime.now(timezone.utc).isoformat()
            _current_run["results"] = results

        # Clean up internal keys
        _current_run.pop("_last_fetched", None)
        _current_run.pop("_last_scored", None)
        _current_run.pop("_last_filtered", None)

    except Exception as exc:
        _current_run["status"] = "error"
        _current_run["error"] = str(exc)
        logger.error("Pipeline run failed: %s", exc, exc_info=True)
    finally:
        _cancel_event = None
        # Auto-clear stale status after 30s so next page load sees "idle"
        async def _clear_stale():
            await asyncio.sleep(30)
            global _current_run
            if _current_run and _current_run.get("run_id") == run_id:
                _current_run = None
        asyncio.create_task(_clear_stale())


@router.post("/run")
async def trigger_pipeline(request: Request, body: PipelineRunBody):
    """Trigger a pipeline run in the background."""
    global _current_run
    if _current_run and _current_run.get("status") == "running":
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")

    config = request.app.state.config
    db_path = request.app.state.db.db_path
    run_id = uuid.uuid4().hex[:12]

    asyncio.create_task(
        _run_pipeline_bg(config, db_path, body.domain, body.hours, run_id)
    )

    return {
        "data": {
            "run_id": run_id,
            "domain": body.domain,
            "hours": body.hours if body.hours > 0 else "auto",
            "status": "started",
        }
    }


@router.post("/cancel")
async def cancel_pipeline():
    """Send a cancel signal to the currently running pipeline."""
    global _cancel_event
    if _cancel_event:
        _cancel_event.set()
        return {"data": {"message": "Cancel signal sent"}}
    return {"data": {"message": "No pipeline running"}}


@router.get("/status")
async def pipeline_status():
    """Current pipeline run status with live progress."""
    if _current_run is None:
        return {"data": {"status": "idle"}}
    # Return a clean copy without internal keys
    clean = {k: v for k, v in _current_run.items() if not k.startswith("_")}
    return {"data": clean}


@router.get("/runs")
async def pipeline_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """Historical pipeline runs."""
    db = request.app.state.db
    try:
        runs = await db.get_pipeline_runs(limit=limit)
        return {"data": runs, "meta": {"total": len(runs)}}
    except Exception as exc:
        logger.error("pipeline_runs error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
