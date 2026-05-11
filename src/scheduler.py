"""InfoHub Scheduler — cron-based periodic pipeline execution.

Uses APScheduler's AsyncIOScheduler with CronTrigger to run the
pipeline for every enabled domain at the configured interval.
"""

import asyncio
import logging
from typing import List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .models import DomainConfig, SchedulerConfig
from .pipeline import InfoHubPipeline

logger = logging.getLogger(__name__)


class InfoHubScheduler:
    """Periodically runs the pipeline for all enabled domains."""

    def __init__(
        self,
        pipeline: InfoHubPipeline,
        domain_configs: List[DomainConfig],
        scheduler_config: SchedulerConfig,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        self.pipeline = pipeline
        self.domain_configs = domain_configs
        self.scheduler_config = scheduler_config
        self.shutdown_event = shutdown_event
        self._scheduler = AsyncIOScheduler()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register the cron job and start the scheduler.

        Does nothing if ``scheduler_config.enabled`` is ``False``.
        """
        if not self.scheduler_config.enabled:
            logger.info("[Scheduler] Disabled by config — skipping start")
            return

        # Parse standard 5-field cron expression: "minute hour day month day_of_week"
        parts = self.scheduler_config.cron.split()
        if len(parts) != 5:
            logger.error(
                "[Scheduler] Invalid cron expression '%s' (expected 5 fields)",
                self.scheduler_config.cron,
            )
            return

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        self._scheduler.add_job(
            self._run_all,
            trigger,
            id="infohub_cron",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("[Scheduler] Started with cron: %s", self.scheduler_config.cron)

    def shutdown(self) -> None:
        """Shut the scheduler down gracefully."""
        try:
            self._scheduler.shutdown(wait=False)
            logger.info("[Scheduler] Shut down")
        except Exception as exc:
            logger.warning("[Scheduler] Error during shutdown: %s", exc)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_all(self) -> None:
        """Execute the pipeline for every enabled domain."""
        hours = self.scheduler_config.default_hours
        logger.info("[Scheduler] Cron fired — running all enabled domains (hours=%d)", hours)

        # Clean up any stale runs from previous crashes before starting
        from .database import cleanup_stale_runs
        cleaned = await cleanup_stale_runs(db_path=self.pipeline.db_path)
        if cleaned:
            logger.warning("[Scheduler] Cleaned up %d stale run(s) before scheduled run", cleaned)

        for dc in self.domain_configs:
            if not dc.enabled:
                continue

            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("[Scheduler] Shutdown requested — stopping scheduled run early")
                break

            try:
                result = await self.pipeline.run(
                    dc, hours=hours, cancel_event=self.shutdown_event
                )
                logger.info("[Scheduler] %s: %s", dc.slug, result)
            except Exception as exc:
                logger.error("[Scheduler] %s failed: %s", dc.slug, exc)
