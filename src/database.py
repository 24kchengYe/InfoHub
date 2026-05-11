"""SQLite storage layer for InfoHub.

Uses aiosqlite with WAL mode for concurrent reads. All datetime
values are stored as UTC ISO-8601 strings. JSON fields (metadata,
ai_tags) are serialised as TEXT.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

import aiosqlite

from .models import ContentItem, SourceType

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DB_PATH = Path("D:/InfoHub/data/infohub.db")


def _utcnow() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    content         TEXT,
    author          TEXT,
    published_at    TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    metadata        TEXT DEFAULT '{}',
    ai_score        REAL,
    ai_reason       TEXT,
    ai_summary      TEXT,
    ai_tags         TEXT DEFAULT '[]',
    domain          TEXT,
    is_read         INTEGER DEFAULT 0,
    is_starred      INTEGER DEFAULT 0,
    cluster_id      TEXT,
    stage           TEXT,
    pipeline_run_id TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_items_domain       ON items(domain);
CREATE INDEX IF NOT EXISTS idx_items_source_type   ON items(source_type);
CREATE INDEX IF NOT EXISTS idx_items_ai_score      ON items(ai_score);
CREATE INDEX IF NOT EXISTS idx_items_published_at  ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_is_read       ON items(is_read);
CREATE INDEX IF NOT EXISTS idx_items_is_starred    ON items(is_starred);
CREATE INDEX IF NOT EXISTS idx_items_pipeline_run  ON items(pipeline_run_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_url_unique ON items(url);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          TEXT PRIMARY KEY,
    domain          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    hours           INTEGER DEFAULT 24,
    raw_count       INTEGER DEFAULT 0,
    scored_count    INTEGER DEFAULT 0,
    filtered_count  INTEGER DEFAULT 0,
    enriched_count  INTEGER DEFAULT 0,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_domain ON pipeline_runs(domain);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    domain          TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'zh',
    markdown        TEXT NOT NULL,
    item_count      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(date, domain, language)
);

CREATE TABLE IF NOT EXISTS domains (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    icon            TEXT DEFAULT '',
    color           TEXT DEFAULT '#6366f1',
    enabled         INTEGER DEFAULT 1,
    sort_order      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS trade_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL,
    date            TEXT NOT NULL,
    signals         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(domain, date)
);
"""


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

async def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables and indexes if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


class _connect:
    """Async context manager that opens a fresh aiosqlite connection."""

    def __init__(self, db_path: Path = DB_PATH):
        self._path = db_path
        self._db = None

    async def __aenter__(self):
        self._db = await aiosqlite.connect(str(self._path))
        await self._db.execute("PRAGMA journal_mode = WAL")
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.execute("PRAGMA busy_timeout = 10000")  # Wait up to 10s for locks
        self._db.row_factory = aiosqlite.Row
        return self._db

    async def __aexit__(self, *exc):
        if self._db:
            await self._db.close()


# ---------------------------------------------------------------------------
# Item helpers
# ---------------------------------------------------------------------------

def _item_to_row(item: ContentItem, stage: Optional[str] = None,
                 run_id: Optional[str] = None) -> Dict[str, Any]:
    """Convert a ContentItem to a dict suitable for SQL parameters."""
    return {
        "id": item.id,
        "source_type": item.source_type.value,
        "title": item.title,
        "url": str(item.url),
        "content": item.content,
        "author": item.author,
        "published_at": item.published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at": item.fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": json.dumps(item.metadata, ensure_ascii=False),
        "ai_score": item.ai_score,
        "ai_reason": item.ai_reason,
        "ai_summary": item.ai_summary,
        "ai_tags": json.dumps(item.ai_tags, ensure_ascii=False),
        "domain": item.domain,
        "is_read": int(item.is_read),
        "is_starred": int(item.is_starred),
        "cluster_id": item.cluster_id,
        "stage": stage or item.stage,
        "pipeline_run_id": run_id or item.pipeline_run_id,
        "created_at": _utcnow(),
    }


def _row_to_item(row: aiosqlite.Row) -> ContentItem:
    """Reconstruct a ContentItem from a database row."""
    d = dict(row)
    d["metadata"] = json.loads(d.get("metadata") or "{}")
    d["ai_tags"] = json.loads(d.get("ai_tags") or "[]")
    d["is_read"] = bool(d.get("is_read", 0))
    d["is_starred"] = bool(d.get("is_starred", 0))
    d["source_type"] = SourceType(d["source_type"])
    # Remove created_at as it's not part of the Pydantic model
    d.pop("created_at", None)
    return ContentItem(**d)


# ---------------------------------------------------------------------------
# Items CRUD
# ---------------------------------------------------------------------------

async def upsert_items(
    items: List[ContentItem],
    stage: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> int:
    """Insert or update items in batch. Returns the number of rows affected."""
    if not items:
        return 0

    sql = """
    INSERT INTO items (
        id, source_type, title, url, content, author,
        published_at, fetched_at, metadata,
        ai_score, ai_reason, ai_summary, ai_tags,
        domain, is_read, is_starred, cluster_id,
        stage, pipeline_run_id, created_at
    ) VALUES (
        :id, :source_type, :title, :url, :content, :author,
        :published_at, :fetched_at, :metadata,
        :ai_score, :ai_reason, :ai_summary, :ai_tags,
        :domain, :is_read, :is_starred, :cluster_id,
        :stage, :pipeline_run_id, :created_at
    )
    ON CONFLICT(id) DO UPDATE SET
        title           = excluded.title,
        content         = excluded.content,
        author          = excluded.author,
        metadata        = excluded.metadata,
        ai_score        = COALESCE(excluded.ai_score, items.ai_score),
        ai_reason       = COALESCE(excluded.ai_reason, items.ai_reason),
        ai_summary      = COALESCE(excluded.ai_summary, items.ai_summary),
        ai_tags         = CASE WHEN excluded.ai_tags != '[]' THEN excluded.ai_tags ELSE items.ai_tags END,
        domain          = COALESCE(excluded.domain, items.domain),
        cluster_id      = COALESCE(excluded.cluster_id, items.cluster_id),
        stage           = COALESCE(excluded.stage, items.stage),
        pipeline_run_id = COALESCE(excluded.pipeline_run_id, items.pipeline_run_id)
    """

    rows = [_item_to_row(item, stage, run_id) for item in items]
    async with _connect(db_path) as db:
        count = 0
        for row in rows:
            try:
                await db.execute(sql, row)
                count += 1
            except Exception:
                pass  # Skip URL conflicts silently
        await db.commit()
    return count


async def get_items(
    domain: Optional[str] = None,
    source: Optional[str] = None,
    min_score: Optional[float] = None,
    search: Optional[str] = None,
    is_read: Optional[bool] = None,
    days: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort: str = "published_at",
    page: int = 1,
    per_page: int = 20,
    category: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    """Paginated item query. Returns {items, total, page, per_page}."""
    conditions: List[str] = []
    params: Dict[str, Any] = {}

    if domain:
        conditions.append("domain = :domain")
        params["domain"] = domain
    if source:
        conditions.append("source_type = :source")
        params["source"] = source
    if min_score is not None:
        conditions.append("ai_score >= :min_score")
        params["min_score"] = min_score
    if category:
        conditions.append("json_extract(metadata, '$.category') = :category")
        params["category"] = category
    if search:
        conditions.append(
            "(title LIKE :search OR content LIKE :search"
            " OR ai_summary LIKE :search"
            " OR metadata LIKE :search)"
        )
        params["search"] = f"%{search}%"
    if is_read is not None:
        conditions.append("is_read = :is_read")
        params["is_read"] = int(is_read)
    if days is not None and days > 0:
        conditions.append("published_at >= datetime('now', :days_offset)")
        params["days_offset"] = f"-{days} days"
    if date_from:
        conditions.append("published_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("published_at < datetime(:date_to, '+1 day')")
        params["date_to"] = date_to

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Validate sort column
    allowed_sorts = {
        "published_at", "fetched_at", "ai_score", "title", "created_at",
    }
    if sort.lstrip("-") not in allowed_sorts:
        sort = "published_at"
    direction = "DESC" if sort.startswith("-") or sort in ("published_at", "fetched_at", "ai_score", "created_at") else "ASC"
    sort_col = sort.lstrip("-")

    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    async with _connect(db_path) as db:
        # Total count
        row = await db.execute_fetchall(
            f"SELECT COUNT(*) as cnt FROM items {where}", params
        )
        total = row[0][0] if row else 0

        # Data
        rows = await db.execute_fetchall(
            f"SELECT * FROM items {where} ORDER BY {sort_col} {direction} LIMIT :limit OFFSET :offset",
            params,
        )

    items = [_row_to_item(r) for r in rows]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


async def get_item(item_id: str, db_path: Path = DB_PATH) -> Optional[ContentItem]:
    """Fetch a single item by ID."""
    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        )
    if not rows:
        return None
    return _row_to_item(rows[0])


async def update_item_read(
    item_id: str, is_read: bool, db_path: Path = DB_PATH
) -> bool:
    """Update the read status of a single item. Returns True if updated."""
    async with _connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE items SET is_read = ? WHERE id = ?",
            (int(is_read), item_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def batch_update_read(
    ids: List[str], is_read: bool, db_path: Path = DB_PATH
) -> int:
    """Batch update read status. Returns the number of rows updated."""
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    async with _connect(db_path) as db:
        cursor = await db.execute(
            f"UPDATE items SET is_read = ? WHERE id IN ({placeholders})",
            [int(is_read)] + ids,
        )
        await db.commit()
        return cursor.rowcount


# ---------------------------------------------------------------------------
# Pipeline runs
# ---------------------------------------------------------------------------

async def save_pipeline_run(
    run_id: str,
    domain: str,
    started_at: str,
    completed_at: Optional[str] = None,
    status: str = "running",
    hours: int = 24,
    raw_count: int = 0,
    scored_count: int = 0,
    filtered_count: int = 0,
    enriched_count: int = 0,
    error_message: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    """Insert or update a pipeline run record."""
    sql = """
    INSERT INTO pipeline_runs (
        run_id, domain, started_at, completed_at, status,
        hours, raw_count, scored_count, filtered_count, enriched_count,
        error_message
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(run_id) DO UPDATE SET
        completed_at   = excluded.completed_at,
        status         = excluded.status,
        raw_count      = excluded.raw_count,
        scored_count   = excluded.scored_count,
        filtered_count = excluded.filtered_count,
        enriched_count = excluded.enriched_count,
        error_message  = excluded.error_message
    """
    async with _connect(db_path) as db:
        await db.execute(sql, (
            run_id, domain, started_at, completed_at, status,
            hours, raw_count, scored_count, filtered_count, enriched_count,
            error_message,
        ))
        await db.commit()


async def get_pipeline_runs(
    limit: int = 20, db_path: Path = DB_PATH
) -> List[Dict[str, Any]]:
    """Return recent pipeline runs ordered by started_at DESC."""
    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in rows]


async def cleanup_stale_runs(
    domain: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> int:
    """Mark stale 'running' pipeline runs as 'interrupted'.

    Should be called before starting a new run for a domain to ensure
    previous runs that crashed or were force-killed are cleaned up.
    """
    async with _connect(db_path) as db:
        if domain:
            cursor = await db.execute(
                """UPDATE pipeline_runs
                   SET status = 'interrupted',
                       completed_at = ?,
                       error_message = ?
                   WHERE domain = ? AND status = 'running'""",
                (_utcnow(), "Pipeline was interrupted (stale run cleaned up on restart)", domain),
            )
        else:
            cursor = await db.execute(
                """UPDATE pipeline_runs
                   SET status = 'interrupted',
                       completed_at = ?,
                       error_message = ?
                   WHERE status = 'running'""",
                (_utcnow(), "Pipeline was interrupted (stale run cleaned up on restart)"),
            )
        await db.commit()
        return cursor.rowcount


async def is_pipeline_running(
    domain: str,
    db_path: Path = DB_PATH,
) -> bool:
    """Check if a pipeline is currently running for the given domain."""
    async with _connect(db_path) as db:
        row = await db.execute_fetchall(
            "SELECT COUNT(*) FROM pipeline_runs WHERE domain = ? AND status = 'running'",
            (domain,),
        )
        return row[0][0] > 0 if row else False


# ---------------------------------------------------------------------------
# Daily summaries
# ---------------------------------------------------------------------------

async def save_daily_summary(
    date: str,
    domain: str,
    language: str,
    markdown: str,
    count: int,
    db_path: Path = DB_PATH,
) -> None:
    """Insert or replace a daily summary."""
    sql = """
    INSERT INTO daily_summaries (date, domain, language, markdown, item_count, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(date, domain, language) DO UPDATE SET
        markdown   = excluded.markdown,
        item_count = excluded.item_count,
        created_at = excluded.created_at
    """
    async with _connect(db_path) as db:
        await db.execute(sql, (date, domain, language, markdown, count, _utcnow()))
        await db.commit()


async def get_daily_summary(
    date: str,
    domain: str,
    language: str = "zh",
    db_path: Path = DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Get a specific daily summary."""
    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM daily_summaries WHERE date = ? AND domain = ? AND language = ?",
            (date, domain, language),
        )
    if not rows:
        return None
    return dict(rows[0])


# ---------------------------------------------------------------------------
# Trade signals
# ---------------------------------------------------------------------------

async def save_trade_signals(
    domain: str,
    date: str,
    signals: list,
    db_path: Path = DB_PATH,
) -> None:
    """Save trade signals for a domain/date."""
    async with _connect(db_path) as db:
        await db.execute(
            """INSERT INTO trade_signals (domain, date, signals, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(domain, date) DO UPDATE SET
                signals = excluded.signals,
                created_at = excluded.created_at""",
            (domain, date, json.dumps(signals, ensure_ascii=False), _utcnow()),
        )
        await db.commit()


async def get_trade_signals(
    domain: str = "finance",
    limit: int = 7,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """Get recent trade signals."""
    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM trade_signals WHERE domain = ? ORDER BY date DESC LIMIT ?",
            (domain, limit),
        )
    result = []
    for r in rows:
        d = dict(r)
        d["signals"] = json.loads(d.get("signals") or "[]")
        d.pop("id", None)
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

async def get_stats(
    domain: Optional[str] = None,
    days: int = 7,
    db_path: Path = DB_PATH,
) -> Dict[str, Any]:
    """Aggregate statistics for the dashboard."""
    conditions: List[str] = []
    params: List[Any] = []

    if domain:
        conditions.append("domain = ?")
        params.append(domain)

    conditions.append("created_at >= datetime('now', ?)")
    params.append(f"-{days} days")

    where = f"WHERE {' AND '.join(conditions)}"

    async with _connect(db_path) as db:
        # Total items
        row = await db.execute_fetchall(
            f"SELECT COUNT(*) FROM items {where}", params
        )
        total = row[0][0] if row else 0

        # Unread
        row = await db.execute_fetchall(
            f"SELECT COUNT(*) FROM items {where} AND is_read = 0", params
        )
        unread = row[0][0] if row else 0

        # Starred
        row = await db.execute_fetchall(
            f"SELECT COUNT(*) FROM items {where} AND is_starred = 1", params
        )
        starred = row[0][0] if row else 0

        # By source
        rows = await db.execute_fetchall(
            f"SELECT source_type, COUNT(*) as cnt FROM items {where} GROUP BY source_type",
            params,
        )
        by_source = {r[0]: r[1] for r in rows}

        # Average score
        row = await db.execute_fetchall(
            f"SELECT AVG(ai_score) FROM items {where} AND ai_score IS NOT NULL",
            params,
        )
        avg_score = round(row[0][0], 2) if row and row[0][0] else None

        # Pipeline runs
        pr_params: List[Any] = []
        pr_where = ""
        if domain:
            pr_where = "WHERE domain = ?"
            pr_params.append(domain)
        row = await db.execute_fetchall(
            f"SELECT COUNT(*) FROM pipeline_runs {pr_where}", pr_params
        )
        run_count = row[0][0] if row else 0

    return {
        "total": total,
        "unread": unread,
        "starred": starred,
        "by_source": by_source,
        "avg_score": avg_score,
        "pipeline_runs": run_count,
        "days": days,
    }


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------

async def get_domain_list(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Return all registered domains ordered by sort_order."""
    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM domains ORDER BY sort_order ASC, slug ASC"
        )
    return [dict(r) for r in rows]


async def save_domain(
    slug: str,
    name: str,
    icon: str = "",
    color: str = "#6366f1",
    enabled: bool = True,
    sort_order: int = 0,
    db_path: Path = DB_PATH,
) -> None:
    """Insert or update a domain record."""
    sql = """
    INSERT INTO domains (slug, name, icon, color, enabled, sort_order, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(slug) DO UPDATE SET
        name       = excluded.name,
        icon       = excluded.icon,
        color      = excluded.color,
        enabled    = excluded.enabled,
        sort_order = excluded.sort_order
    """
    async with _connect(db_path) as db:
        await db.execute(sql, (slug, name, icon, color, int(enabled), sort_order, _utcnow()))
        await db.commit()


async def clear_all_data(db_path: Path = DB_PATH) -> None:
    """Delete all items, pipeline runs, and daily summaries."""
    async with _connect(db_path) as db:
        await db.execute("DELETE FROM items")
        await db.execute("DELETE FROM pipeline_runs")
        await db.execute("DELETE FROM daily_summaries")
        await db.commit()


async def get_daily_summaries(
    limit: int = 20, db_path: Path = DB_PATH
) -> List[Dict[str, Any]]:
    """Return recent daily summaries ordered by date DESC."""
    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM daily_summaries ORDER BY date DESC, domain ASC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in rows]


async def update_item(
    item_id: str, updates: Dict[str, Any], db_path: Path = DB_PATH
) -> bool:
    """Update arbitrary fields on a single item. Returns True if updated."""
    if not updates:
        return False
    set_parts = []
    params: List[Any] = []
    for key, value in updates.items():
        if key in ("is_read", "is_starred"):
            set_parts.append(f"{key} = ?")
            params.append(int(value))
        elif key in ("ai_score", "ai_reason", "ai_summary", "domain", "stage", "cluster_id"):
            set_parts.append(f"{key} = ?")
            params.append(value)
    if not set_parts:
        return False
    params.append(item_id)
    async with _connect(db_path) as db:
        cursor = await db.execute(
            f"UPDATE items SET {', '.join(set_parts)} WHERE id = ?", params
        )
        await db.commit()
        return cursor.rowcount > 0


async def batch_update_items(
    ids: List[str], updates: Dict[str, Any], db_path: Path = DB_PATH
) -> int:
    """Batch update fields on multiple items."""
    if not ids or not updates:
        return 0
    if "is_read" in updates:
        return await batch_update_read(ids, updates["is_read"], db_path)
    return 0


async def get_daily_trend(
    domain: Optional[str] = None,
    days: int = 14,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """Return per-day item counts for the past N days (by published_at)."""
    conditions = ["published_at >= datetime('now', ?)"]
    params: List[Any] = [f"-{days} days"]
    if domain:
        conditions.append("domain = ?")
        params.append(domain)
    where = "WHERE " + " AND ".join(conditions)

    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            f"SELECT date(published_at) as day, COUNT(*) as count FROM items {where} GROUP BY date(published_at) ORDER BY day ASC",
            params,
        )
    return [{"day": r[0], "count": r[1]} for r in rows if r[0]]


async def get_score_distribution(
    domain: Optional[str] = None,
    days: int = 7,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """Return score distribution in buckets: 0-2, 2-4, 4-6, 6-8, 8-10."""
    conditions = ["ai_score IS NOT NULL", "created_at >= datetime('now', ?)"]
    params: List[Any] = [f"-{days} days"]
    if domain:
        conditions.append("domain = ?")
        params.append(domain)
    where = "WHERE " + " AND ".join(conditions)

    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            f"""SELECT
                CASE
                    WHEN ai_score < 2 THEN '0-2'
                    WHEN ai_score < 4 THEN '2-4'
                    WHEN ai_score < 6 THEN '4-6'
                    WHEN ai_score < 8 THEN '6-8'
                    ELSE '8-10'
                END as bucket,
                COUNT(*) as count
            FROM items {where}
            GROUP BY bucket
            ORDER BY bucket ASC""",
            params,
        )
    return [{"bucket": r[0], "count": r[1]} for r in rows]


async def get_source_breakdown(
    domain: Optional[str] = None,
    days: int = 7,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """Return item counts per feed/source name."""
    conditions = ["created_at >= datetime('now', ?)"]
    params: List[Any] = [f"-{days} days"]
    if domain:
        conditions.append("domain = ?")
        params.append(domain)
    where = "WHERE " + " AND ".join(conditions)

    async with _connect(db_path) as db:
        rows = await db.execute_fetchall(
            f"""SELECT
                source_type,
                COALESCE(json_extract(metadata, '$.feed_name'), source_type) as source_name,
                COUNT(*) as count
            FROM items {where}
            GROUP BY source_type, source_name
            ORDER BY count DESC""",
            params,
        )
    return [{"source_type": r[0], "source_name": r[1], "count": r[2]} for r in rows]


async def update_pipeline_run(
    run_id: str,
    status: str,
    raw_count: int = 0,
    scored_count: int = 0,
    filtered_count: int = 0,
    enriched_count: int = 0,
    error_message: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    """Update an existing pipeline run record."""
    completed_at = _utcnow() if status in ("completed", "failed") else None
    async with _connect(db_path) as db:
        await db.execute(
            """UPDATE pipeline_runs SET
                completed_at = ?, status = ?,
                raw_count = ?, scored_count = ?,
                filtered_count = ?, enriched_count = ?,
                error_message = ?
            WHERE run_id = ?""",
            (completed_at, status, raw_count, scored_count,
             filtered_count, enriched_count, error_message, run_id),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Database convenience wrapper (used by API routes via app.state.db)
# ---------------------------------------------------------------------------

class Database:
    """Thin wrapper that delegates to the module-level async functions."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    async def init_db(self):
        await init_db(self.db_path)

    async def get_items(self, **kw):
        return await get_items(db_path=self.db_path, **kw)

    async def get_item(self, item_id):
        return await get_item(item_id, db_path=self.db_path)

    async def update_item(self, item_id, updates):
        return await update_item(item_id, updates, db_path=self.db_path)

    async def batch_update_items(self, ids, updates):
        return await batch_update_items(ids, updates, db_path=self.db_path)

    async def upsert_items(self, items, **kw):
        return await upsert_items(items, db_path=self.db_path, **kw)

    async def save_pipeline_run(self, run_id, domain, started_at, **kw):
        return await save_pipeline_run(run_id, domain, started_at, db_path=self.db_path, **kw)

    async def get_pipeline_runs(self, limit=20):
        return await get_pipeline_runs(limit, db_path=self.db_path)

    async def save_daily_summary(self, date, domain, language, markdown, count):
        return await save_daily_summary(date, domain, language, markdown, count, db_path=self.db_path)

    async def get_daily_summary(self, date, domain, language="zh"):
        return await get_daily_summary(date, domain, language, db_path=self.db_path)

    async def get_daily_summaries(self, limit=20):
        return await get_daily_summaries(limit, db_path=self.db_path)

    async def get_stats(self, domain=None, days=7):
        return await get_stats(domain, days, db_path=self.db_path)

    async def get_domain_list(self):
        return await get_domain_list(db_path=self.db_path)

    async def get_daily_trend(self, domain=None, days=14):
        return await get_daily_trend(domain, days, db_path=self.db_path)

    async def get_score_distribution(self, domain=None, days=7):
        return await get_score_distribution(domain, days, db_path=self.db_path)

    async def get_source_breakdown(self, domain=None, days=7):
        return await get_source_breakdown(domain, days, db_path=self.db_path)

    async def clear_all_data(self):
        return await clear_all_data(db_path=self.db_path)

    async def save_domain(self, slug, name, icon="", color="#6366f1"):
        return await save_domain(slug, name, icon, color, db_path=self.db_path)

    async def save_trade_signals(self, domain, date, signals):
        return await save_trade_signals(domain, date, signals, db_path=self.db_path)

    async def get_trade_signals(self, domain="finance", limit=7):
        return await get_trade_signals(domain, limit, db_path=self.db_path)
