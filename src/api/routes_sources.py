"""Source management routes — CRUD for domain config JSON files."""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("infohub.api.sources")
router = APIRouter(prefix="/api/sources", tags=["sources"])

DOMAINS_DIR = Path("D:/InfoHub/data/domains")


class RssSource(BaseModel):
    name: str
    url: str
    category: Optional[str] = None
    enabled: bool = True


class AddRssBody(BaseModel):
    domain: str  # domain slug, e.g. "ai"
    name: str
    url: str
    category: Optional[str] = None


class RemoveRssBody(BaseModel):
    domain: str
    url: str  # identify by URL


@router.get("")
async def list_all_sources():
    """List all sources grouped by domain."""
    result = []
    for f in sorted(DOMAINS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sources = data.get("sources", {})
            domain_info = {
                "slug": data.get("slug", f.stem),
                "name": data.get("name", f.stem),
                "icon": data.get("icon", ""),
                "rss": sources.get("rss", []),
                "hackernews": sources.get("hackernews", {}),
                "reddit": sources.get("reddit", {}),
                "github": sources.get("github", []),
                "twitter": sources.get("twitter", {}),
                "telegram": sources.get("telegram", {}),
            }
            result.append(domain_info)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", f.name, exc)
    return {"data": result}


@router.get("/{domain_slug}")
async def get_domain_sources(domain_slug: str):
    """Get sources for a specific domain."""
    f = DOMAINS_DIR / f"{domain_slug}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail=f"Domain '{domain_slug}' not found")
    data = json.loads(f.read_text(encoding="utf-8"))
    return {"data": data}


@router.post("/rss/add")
async def add_rss_source(body: AddRssBody):
    """Add an RSS source to a domain."""
    f = DOMAINS_DIR / f"{body.domain}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail=f"Domain '{body.domain}' not found")

    data = json.loads(f.read_text(encoding="utf-8"))
    rss_list = data.setdefault("sources", {}).setdefault("rss", [])

    # Check duplicate
    for existing in rss_list:
        if existing.get("url") == body.url:
            raise HTTPException(status_code=409, detail="RSS source already exists")

    rss_list.append({
        "name": body.name,
        "url": body.url,
        "category": body.category,
    })

    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"data": {"message": f"Added '{body.name}' to {body.domain}", "total_rss": len(rss_list)}}


@router.post("/rss/remove")
async def remove_rss_source(body: RemoveRssBody):
    """Remove an RSS source from a domain by URL."""
    f = DOMAINS_DIR / f"{body.domain}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail=f"Domain '{body.domain}' not found")

    data = json.loads(f.read_text(encoding="utf-8"))
    rss_list = data.get("sources", {}).get("rss", [])

    original_len = len(rss_list)
    rss_list = [r for r in rss_list if r.get("url") != body.url]

    if len(rss_list) == original_len:
        raise HTTPException(status_code=404, detail="RSS source not found")

    data["sources"]["rss"] = rss_list
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"data": {"message": "Removed", "total_rss": len(rss_list)}}
