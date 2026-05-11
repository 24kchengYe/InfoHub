"""InfoHub Pipeline — fetch -> score -> filter -> enrich -> summarize.

Orchestrates the end-to-end content processing flow for a single domain.
Each run is tracked by a unique run_id stored in the pipeline_runs table.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import List, Optional

import httpx

from .models import (
    Config,
    ContentItem,
    DomainConfig,
    GlobalConfig,
    SourcesConfig,
)
from .database import (
    upsert_items,
    save_pipeline_run,
    save_daily_summary,
)
from .scrapers.github import GitHubScraper
from .scrapers.hackernews import HackerNewsScraper
from .scrapers.rss import RSSScraper
from .scrapers.reddit import RedditScraper
from .scrapers.telegram import TelegramScraper
from .scrapers.twitter import TwitterScraper
from .ai.client import create_ai_client
from .ai.analyzer import ContentAnalyzer
from .ai.enricher import ContentEnricher
from .ai.summarizer import DailySummarizer

logger = logging.getLogger(__name__)


class PipelineCancelled(Exception):
    """Raised when a pipeline run is cancelled via cancel_event."""
    pass


class InfoHubPipeline:
    """End-to-end pipeline: fetch -> score -> filter -> enrich -> summarize."""

    def __init__(self, db_path=None, global_config: Optional[GlobalConfig] = None):
        """Initialise the pipeline.

        Args:
            db_path: Optional override for the SQLite database path.
            global_config: Top-level InfoHub configuration.
        """
        from pathlib import Path
        self.db_path = db_path or Path("D:/InfoHub/data/infohub.db")
        self.global_config = global_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, domain_config: DomainConfig, hours: int = 24,
                  on_progress=None, cancel_event: asyncio.Event = None) -> dict:
        """Run the complete pipeline for *domain_config*.

        Args:
            on_progress: Optional callback(phase, detail) for live progress updates.
                         phase is a string tag; detail is a dict with context info.
            cancel_event: Optional asyncio.Event — when set, the pipeline will
                          raise PipelineCancelled at the next checkpoint.

        Returns a dict with run_id, status, raw / scored / filtered counts.
        """
        _progress = on_progress or (lambda *_: None)

        def _check_cancelled(stage: str = ""):
            if cancel_event and cancel_event.is_set():
                raise PipelineCancelled(f"cancelled during {stage}" if stage else "cancelled")

        # 0. Clean up stale runs and prevent concurrent execution for the same domain
        from .database import cleanup_stale_runs, is_pipeline_running
        stale_count = await cleanup_stale_runs(domain_config.slug, db_path=self.db_path)
        if stale_count:
            logger.warning("[Pipeline] Cleaned up %d stale run(s) for %s",
                          stale_count, domain_config.slug)

        if await is_pipeline_running(domain_config.slug, db_path=self.db_path):
            logger.warning("[Pipeline] %s: another run is already in progress, skipping",
                          domain_config.slug)
            return {"run_id": None, "status": "skipped", "reason": "another run is in progress"}

        run_id = f"run-{datetime.utcnow():%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Track active run for graceful-shutdown bookkeeping
        InfoHubPipeline._active_run = {
            "run_id": run_id,
            "domain": domain_config.slug,
            "db_path": self.db_path,
            "started_at": started_at,
        }

        # 1. Record pipeline run as "running"
        await save_pipeline_run(
            run_id=run_id,
            domain=domain_config.slug,
            started_at=started_at,
            status="running",
            hours=hours,
            db_path=self.db_path,
        )

        try:
            _check_cancelled("init")

            # 2. Build a Horizon-compatible Config for scrapers / AI
            config = self._build_config(domain_config)

            # 3. Serial fetch from all configured sources (one by one for
            #    cancel support and per-source progress reporting)
            # Use at least 168h (7 days) window to catch slow-updating blogs
            fetch_hours = max(hours, 168)
            since = datetime.now(timezone.utc) - timedelta(hours=fetch_hours)
            raw_items = await self._fetch_all_sources(
                config.sources, since,
                on_progress=_progress,
                cancel_event=cancel_event,
            )
            logger.info("[Pipeline] %s: fetched %d raw items", domain_config.slug, len(raw_items))

            _check_cancelled("after fetch")

            # 4. URL deduplication (within this batch)
            merged = self._merge_duplicates(raw_items)

            # Tag every item with the domain slug
            for item in merged:
                item.domain = domain_config.slug

            # 5. Dedup against DB by URL — split into new vs already-scored
            from .database import _connect
            import json as _json

            already_scored: List[ContentItem] = []
            new_items: List[ContentItem] = []

            if merged:
                # Batch query: find all URLs that already exist and are scored
                urls = [str(item.url) for item in merged]
                async with _connect(self.db_path) as db:
                    # SQLite has a variable limit, batch in chunks of 500
                    scored_url_map: dict = {}
                    for i in range(0, len(urls), 500):
                        chunk = urls[i:i+500]
                        placeholders = ",".join("?" for _ in chunk)
                        rows = await db.execute_fetchall(
                            f"SELECT url, ai_score, ai_reason, ai_summary, ai_tags, metadata "
                            f"FROM items WHERE url IN ({placeholders}) AND ai_score IS NOT NULL",
                            chunk,
                        )
                        for r in rows:
                            scored_url_map[r[0]] = {
                                "ai_score": r[1], "ai_reason": r[2],
                                "ai_summary": r[3], "ai_tags": r[4], "metadata": r[5],
                            }

                for item in merged:
                    existing = scored_url_map.get(str(item.url))
                    if existing:
                        item.ai_score = existing["ai_score"]
                        item.ai_reason = existing["ai_reason"]
                        item.ai_summary = existing["ai_summary"]
                        item.ai_tags = _json.loads(existing["ai_tags"] or "[]")
                        old_meta = _json.loads(existing["metadata"] or "{}")
                        item.metadata = {**item.metadata, **old_meta}
                        already_scored.append(item)
                    else:
                        new_items.append(item)

            logger.info("[Pipeline] %s: %d fetched, %d already in DB, %d new to process",
                       domain_config.slug, len(merged), len(already_scored), len(new_items))
            _progress("fetch_done", {"count": len(new_items)})

            # Only persist new items
            if new_items:
                await upsert_items(new_items, stage="raw", run_id=run_id, db_path=self.db_path)

            _check_cancelled("before scoring")

            # 6. AI scoring — concurrent LLM calls + batched DB writes
            needs_scoring = new_items
            scored: List[ContentItem] = list(already_scored)
            score_semaphore = asyncio.Semaphore(15)  # 15 concurrent LLM calls
            score_done_count = 0
            score_queue: List[ContentItem] = []  # batch write queue

            async def _flush_score_queue():
                """Batch write scored items to DB."""
                nonlocal score_queue
                if score_queue:
                    batch = list(score_queue)
                    score_queue.clear()
                    await upsert_items(batch, stage="scored", run_id=run_id, db_path=self.db_path)

            async def _score_one(analyzer, item):
                nonlocal score_done_count
                async with score_semaphore:
                    _check_cancelled("scoring")
                    try:
                        await analyzer._analyze_item(item)
                    except Exception as e:
                        logger.warning("[Pipeline] Scoring item %s failed: %s", item.id, e)
                        item.ai_score = 0.0
                        item.ai_reason = f"Analysis failed: {e}"
                        item.ai_summary = item.title
                    score_queue.append(item)
                    score_done_count += 1
                    _progress("score_item", {"index": score_done_count, "total": len(needs_scoring)})
                    # Flush every 10 items
                    if len(score_queue) >= 10:
                        await _flush_score_queue()
                    # Yield to event loop so API requests can be served
                    await asyncio.sleep(0)

            try:
                ai_client = create_ai_client(config.ai)
                analyzer = ContentAnalyzer(ai_client)
                tasks = [_score_one(analyzer, item) for item in needs_scoring]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                await _flush_score_queue()  # flush remaining
                for item in needs_scoring:
                    scored.append(item)
                for r in results:
                    if isinstance(r, PipelineCancelled):
                        raise r
            except PipelineCancelled:
                await _flush_score_queue()
                raise
            except Exception as exc:
                logger.error("[Pipeline] AI scoring failed: %s", exc)
                scored = merged

            _progress("score_done", {"count": len(scored)})

            # 6b. Sentiment analysis for finance domain (concurrent, only new items)
            if domain_config.slug == "finance" and needs_scoring:
                try:
                    from .trading.sentiment import SentimentAnalyzer
                    ai_client_sentiment = create_ai_client(config.ai)
                    sa = SentimentAnalyzer(ai_client=ai_client_sentiment)
                    sent_semaphore = asyncio.Semaphore(20)

                    async def _analyze_sentiment(item):
                        async with sent_semaphore:
                            result = await sa.analyze_async(item)
                            if result:
                                item.metadata["sentiment"] = result.sentiment.value
                                item.metadata["sentiment_confidence"] = result.confidence
                                item.metadata["tickers"] = result.tickers
                                item.metadata["sentiment_impact"] = result.impact
                                item.metadata["sentiment_time_horizon"] = result.time_horizon
                                item.metadata["sentiment_reasoning"] = result.reasoning

                    # Only analyze newly scored items (not already_scored)
                    await asyncio.gather(*[_analyze_sentiment(item) for item in needs_scoring], return_exceptions=True)
                except Exception as exc:
                    logger.warning("[Pipeline] Sentiment analysis failed (non-fatal): %s", exc)

            _check_cancelled("before filtering")

            # 7. Filter by AI score threshold
            threshold = domain_config.filtering.ai_score_threshold
            important = [
                i for i in scored
                if i.ai_score is not None and i.ai_score >= threshold
            ]
            important.sort(key=lambda x: x.ai_score or 0, reverse=True)
            _progress("filter_done", {"count": len(important)})

            _check_cancelled("before enrichment")

            # 8. Enrich — only score >= 8, skip already-enriched
            ENRICH_THRESHOLD = 8.0  # Only deep-enrich high-value items
            needs_enrich: List[ContentItem] = []
            already_enriched: List[ContentItem] = []
            skip_enrich: List[ContentItem] = []  # score < 8, skip enrichment
            if important:
                async with _connect(self.db_path) as db:
                    enriched_urls: set = set()
                    urls_to_check = [str(item.url) for item in important]
                    for i in range(0, len(urls_to_check), 500):
                        chunk = urls_to_check[i:i+500]
                        placeholders = ",".join("?" for _ in chunk)
                        rows = await db.execute_fetchall(
                            f"SELECT url FROM items WHERE url IN ({placeholders}) AND stage = 'enriched'",
                            chunk,
                        )
                        enriched_urls.update(r[0] for r in rows)

                for item in important:
                    if str(item.url) in enriched_urls:
                        already_enriched.append(item)
                    elif (item.ai_score or 0) >= ENRICH_THRESHOLD:
                        needs_enrich.append(item)
                    else:
                        skip_enrich.append(item)  # score < 8, skip deep enrichment

            logger.info("[Pipeline] %s: %d already-enriched, %d to enrich (score>=%.0f), %d skipped (score<%.0f)",
                       domain_config.slug, len(already_enriched), len(needs_enrich),
                       ENRICH_THRESHOLD, len(skip_enrich), ENRICH_THRESHOLD)

            # Run enrichment in a thread pool to avoid blocking the event loop
            # (enricher uses sync ddgs search internally)
            from concurrent.futures import ThreadPoolExecutor
            import threading

            enrich_done_count = 0
            enrich_lock = threading.Lock()

            def _enrich_sync(enricher, item, loop):
                nonlocal enrich_done_count
                if cancel_event and cancel_event.is_set():
                    return
                try:
                    # Run the async enrich in a new event loop within this thread
                    import asyncio as _aio
                    _loop = _aio.new_event_loop()
                    try:
                        _loop.run_until_complete(enricher._enrich_item(item))
                    finally:
                        _loop.close()
                except Exception as e:
                    logger.warning("[Pipeline] Enriching item %s failed: %s", item.id, e)
                with enrich_lock:
                    enrich_done_count += 1
                    _progress("enrich_item", {"index": enrich_done_count, "total": len(needs_enrich)})

            try:
                ai_client_enrich = create_ai_client(config.ai)
                enricher = ContentEnricher(ai_client_enrich)
                loop = asyncio.get_event_loop()

                with ThreadPoolExecutor(max_workers=5) as pool:
                    futures = [
                        loop.run_in_executor(pool, _enrich_sync, enricher, item, loop)
                        for item in needs_enrich
                    ]
                    await asyncio.gather(*futures, return_exceptions=True)
            except PipelineCancelled:
                raise
            except Exception as exc:
                logger.warning("[Pipeline] Enrichment failed (non-fatal): %s", exc)

            # 9. Persist all items (enriched + skipped) as "enriched" stage
            all_important = already_enriched + needs_enrich + skip_enrich
            await upsert_items(all_important, stage="enriched", run_id=run_id, db_path=self.db_path)

            # 9b. Generate trade signals for finance domain (using existing sentiment data, no extra LLM calls)
            if domain_config.slug == "finance":
                try:
                    from .trading.sentiment import SentimentAnalyzer, SentimentResult, Sentiment
                    from .trading.signals import TradeSignalGenerator
                    # Use sentiment already computed in step 6b instead of re-analyzing
                    sentiments = []
                    for item in all_important:
                        meta = item.metadata or {}
                        if meta.get("sentiment"):
                            sentiments.append(SentimentResult(
                                item_id=item.id,
                                sentiment=Sentiment(meta["sentiment"]),
                                confidence=meta.get("sentiment_confidence", 0.5),
                                reasoning=meta.get("sentiment_reasoning", ""),
                                tickers=meta.get("tickers", []),
                                impact=meta.get("sentiment_impact", "medium"),
                                time_horizon=meta.get("sentiment_time_horizon", "short"),
                            ))
                    sig_gen = TradeSignalGenerator(min_mentions=1, min_confidence=0.4)
                    signals = sig_gen.generate(sentiments)
                    # Store signals in a special metadata field on the domain's pipeline run
                    if signals:
                        import json
                        signal_data = [
                            {
                                "ticker": s.ticker,
                                "direction": s.direction,
                                "strength": s.strength,
                                "sentiment_count": s.sentiment_count,
                                "avg_confidence": s.avg_confidence,
                                "reasons": s.reasons,
                            }
                            for s in signals
                        ]
                        # Save as a special item in the DB for retrieval
                        from .database import save_trade_signals
                        await save_trade_signals(
                            domain_config.slug,
                            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            signal_data,
                            db_path=self.db_path,
                        )
                        logger.info("[Pipeline] Generated %d trade signals", len(signals))
                except Exception as exc:
                    logger.warning("[Pipeline] Trade signal generation failed (non-fatal): %s", exc)

            _check_cancelled("before summary")

            # 10. Generate daily summaries — only items scoring >= 7
            DAILY_MIN_SCORE = 7.0
            from collections import defaultdict
            date_groups: dict[str, List[ContentItem]] = defaultdict(list)
            for item in all_important:
                if (item.ai_score or 0) < DAILY_MIN_SCORE:
                    continue
                pub_date = item.published_at.strftime("%Y-%m-%d") if item.published_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")
                date_groups[pub_date].append(item)

            from .database import get_items as _get_items
            for date_str, date_items in date_groups.items():
                # Get total items for this date (all scores) for accurate header
                try:
                    _all = await _get_items(
                        domain=domain_config.slug, per_page=1,
                        date_from=date_str, date_to=date_str, db_path=self.db_path,
                    )
                    total_for_day = _all.get("total", len(date_items))
                except Exception:
                    total_for_day = len(date_items)

                for lang in config.ai.languages:
                    try:
                        summarizer = DailySummarizer()
                        summary = await summarizer.generate_summary(
                            date_items, date_str, total_for_day, language=lang,
                        )
                        await save_daily_summary(
                            date_str, domain_config.slug, lang, summary,
                            len(date_items), db_path=self.db_path,
                        )
                    except Exception as exc:
                        logger.warning("[Pipeline] Summary generation failed for %s/%s/%s: %s",
                                      domain_config.slug, date_str, lang, exc)

            # Also regenerate "all" domain daily for each date in this batch
            for date_str in date_groups.keys():
                try:
                    _all_d = await _get_items(per_page=1, date_from=date_str, date_to=date_str, db_path=self.db_path)
                    _hi_d = await _get_items(min_score=DAILY_MIN_SCORE, sort="ai_score", per_page=500,
                                             date_from=date_str, date_to=date_str, db_path=self.db_path)
                    if _hi_d["items"]:
                        for lang in config.ai.languages:
                            summarizer = DailySummarizer()
                            summary = await summarizer.generate_summary(
                                _hi_d["items"], date_str, _all_d.get("total", 0), language=lang,
                            )
                            await save_daily_summary(date_str, "all", lang, summary, len(_hi_d["items"]), db_path=self.db_path)
                except Exception as exc:
                    logger.warning("[Pipeline] 'all' daily generation for %s failed: %s", date_str, exc)

            # 11. Mark run as completed
            completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            await save_pipeline_run(
                run_id=run_id,
                domain=domain_config.slug,
                started_at=started_at,
                completed_at=completed_at,
                status="completed",
                hours=hours,
                raw_count=len(raw_items),
                scored_count=len(scored),
                filtered_count=len(important),
                enriched_count=len(important),
                db_path=self.db_path,
            )

            result = {
                "run_id": run_id,
                "status": "completed",
                "raw": len(raw_items),
                "scored": len(scored),
                "filtered": len(important),
            }
            logger.info("[Pipeline] %s completed: %s", domain_config.slug, result)
            return result

        except PipelineCancelled as exc:
            # Mark run as cancelled (distinct from failed)
            completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            await save_pipeline_run(
                run_id=run_id,
                domain=domain_config.slug,
                started_at=started_at,
                completed_at=completed_at,
                status="cancelled",
                hours=hours,
                error_message=str(exc),
                db_path=self.db_path,
            )
            logger.info("[Pipeline] %s cancelled: %s", domain_config.slug, exc)
            raise

        except Exception as exc:
            # Mark run as failed
            completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            await save_pipeline_run(
                run_id=run_id,
                domain=domain_config.slug,
                started_at=started_at,
                completed_at=completed_at,
                status="failed",
                hours=hours,
                error_message=str(exc),
                db_path=self.db_path,
            )
            logger.error("[Pipeline] %s failed: %s", domain_config.slug, exc)
            raise

        finally:
            # Always clear the active-run tracker
            InfoHubPipeline._active_run = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_config(self, domain_config: DomainConfig) -> Config:
        """Construct a Horizon-compatible Config from global + domain configs."""
        return Config(
            ai=self.global_config.ai,
            sources=domain_config.sources,
            filtering=domain_config.filtering,
        )

    async def _fetch_all_sources(
        self, sources: SourcesConfig, since: datetime,
        on_progress=None, cancel_event: asyncio.Event = None,
    ) -> List[ContentItem]:
        """Fetch from all enabled sources **serially** so we can report
        per-source progress and honour cancel_event between sources.
        """
        import os
        _progress = on_progress or (lambda *_: None)

        # Use HTTP proxy explicitly; ignore ALL_PROXY (may be socks5 which
        # requires socksio).  Fall back to HTTPS_PROXY / HTTP_PROXY env vars.
        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        async with httpx.AsyncClient(timeout=90.0, proxy=proxy_url) as client:
            # Build list of (name, scraper) tuples for enabled sources
            source_list: list = []

            if sources.github:
                source_list.append(("GitHub", GitHubScraper(sources.github, client)))
            if sources.hackernews.enabled:
                source_list.append(("HackerNews", HackerNewsScraper(sources.hackernews, client)))
            if sources.rss:
                for rss_src in sources.rss:
                    if rss_src.enabled:
                        source_list.append((f"RSS · {rss_src.name}", RSSScraper([rss_src], client)))
            if sources.reddit.enabled:
                source_list.append(("Reddit", RedditScraper(sources.reddit, client)))
            if sources.telegram.enabled:
                source_list.append(("Telegram", TelegramScraper(sources.telegram, client)))
            if sources.twitter and sources.twitter.enabled:
                source_list.append(("Twitter", TwitterScraper(sources.twitter, client)))

            total_sources = len(source_list)
            items: List[ContentItem] = []
            fetch_semaphore = asyncio.Semaphore(15)  # 15 concurrent fetches
            fetch_done_count = 0

            async def _fetch_one(name, scraper, idx):
                nonlocal fetch_done_count
                async with fetch_semaphore:
                    if cancel_event and cancel_event.is_set():
                        raise PipelineCancelled("cancelled during fetching")

                    _progress("fetch_source", {
                        "source": name,
                        "index": idx + 1,
                        "total": total_sources,
                        "fetched_so_far": len(items),
                    })

                    fetched = await self._safe_fetch(name, scraper, since)
                    items.extend(fetched)
                    fetch_done_count += 1

                    _progress("fetch_source_done", {
                        "source": name,
                        "index": fetch_done_count,
                        "total": total_sources,
                        "source_count": len(fetched),
                        "fetched_so_far": len(items),
                })

            # Launch all fetches concurrently
            fetch_tasks = [_fetch_one(name, scraper, idx) for idx, (name, scraper) in enumerate(source_list)]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, PipelineCancelled):
                    raise r

            return items

    @staticmethod
    async def _safe_fetch(name: str, scraper, since: datetime) -> List[ContentItem]:
        """Fetch from a single scraper with error handling."""
        try:
            items = await scraper.fetch(since)
            logger.info("[Pipeline] %s: %d items", name, len(items))
            return items
        except Exception as exc:
            logger.error("[Pipeline] %s fetch failed: %s", name, exc)
            return []

    @staticmethod
    def _merge_duplicates(items: List[ContentItem]) -> List[ContentItem]:
        """URL-based deduplication, keeping the first occurrence."""
        seen_urls: set = set()
        merged: List[ContentItem] = []
        for item in items:
            url = str(item.url)
            if url not in seen_urls:
                seen_urls.add(url)
                merged.append(item)
        return merged
