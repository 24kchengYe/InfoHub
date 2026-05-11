"""Domain listing routes."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("infohub.api.domains")
router = APIRouter(prefix="/api", tags=["domains"])

DOMAINS_DIR = Path("D:/InfoHub/data/domains")


@router.get("/domains")
async def list_domains(request: Request):
    """Return all configured domains with categories."""
    db = request.app.state.db
    try:
        domains = await db.get_domain_list()
        # Enrich with categories from JSON config files
        for domain in domains:
            slug = domain.get("slug")
            config_file = DOMAINS_DIR / f"{slug}.json"
            if config_file.exists():
                try:
                    config = json.loads(config_file.read_text(encoding="utf-8"))
                    domain["categories"] = config.get("categories", [])
                except Exception:
                    domain["categories"] = []
            else:
                domain["categories"] = []
        return {
            "data": domains,
            "meta": {"total": len(domains)},
        }
    except Exception as exc:
        logger.error("list_domains error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
