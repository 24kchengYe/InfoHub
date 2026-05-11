"""FastAPI application factory for InfoHub."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import load_global_config, load_domain_configs
from src.database import Database, DB_PATH

from .routes_daily import router as daily_router
from .routes_data import router as data_router
from .routes_domains import router as domains_router
from .routes_items import router as items_router
from .routes_pipeline import router as pipeline_router
from .routes_sources import router as sources_router
from .routes_stats import router as stats_router
from .routes_trading import router as trading_router

logger = logging.getLogger("infohub.api")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    config = load_global_config()
    app.state.config = config

    # Initialise database
    db = Database(DB_PATH)
    await db.init_db()
    app.state.db = db
    logger.info("Database initialised at %s", DB_PATH)

    # Load domain configs into the domains table
    try:
        domain_configs = load_domain_configs()
        for dc in domain_configs:
            await db.save_domain(dc.slug, dc.name, dc.icon, dc.color)
        app.state.domain_configs = domain_configs
        logger.info("Loaded %d domain configs", len(domain_configs))
    except Exception:
        logger.warning("Failed to load domain configs", exc_info=True)
        app.state.domain_configs = []

    # Start scheduler
    scheduler = None
    shutdown_event = asyncio.Event()
    try:
        from src.scheduler import InfoHubScheduler
        from src.pipeline import InfoHubPipeline

        pipeline = InfoHubPipeline(db_path=db.db_path, global_config=config)
        scheduler = InfoHubScheduler(
            pipeline, app.state.domain_configs, config.scheduler,
            shutdown_event=shutdown_event,
        )
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info("Scheduler started (cron: %s)", config.scheduler.cron)
    except Exception:
        logger.warning("Scheduler not started", exc_info=True)

    # Start AutoTrader
    auto_trader = None
    auto_trader_task = None
    try:
        from src.trading.auto_trader import AutoTrader, AutoTraderConfig
        from src.ai.client import create_ai_client
        ai_client = None
        try:
            ai_client = create_ai_client(config.ai)
            logger.info("AI client created for Multi-Agent mode: %s/%s", config.ai.provider, config.ai.model)
        except Exception as ai_exc:
            logger.warning("AI client creation failed (%s), AutoTrader will use formula mode", ai_exc)
        auto_trader = AutoTrader(AutoTraderConfig(enabled=False), ai_client=ai_client)
        app.state.auto_trader = auto_trader

        async def _auto_trader_loop():
            """Background loop: run AutoTrader cycle every 5 minutes when enabled."""
            while not shutdown_event.is_set():
                try:
                    if auto_trader.config.enabled:
                        await auto_trader.run_cycle(db)
                except Exception as exc:
                    logger.error("[AutoTrader] Cycle error: %s", exc, exc_info=True)
                # Wait 5 min or until shutdown
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=300)
                    break  # shutdown signalled
                except asyncio.TimeoutError:
                    pass  # 5 min elapsed, loop again

        auto_trader_task = asyncio.create_task(_auto_trader_loop())
        logger.info("AutoTrader background loop started (disabled by default)")
    except Exception:
        logger.warning("AutoTrader not started", exc_info=True)

    yield

    # Shutdown — signal cancellation to any running pipeline
    logger.info("InfoHub shutting down — signalling pipeline cancellation")
    shutdown_event.set()
    if auto_trader_task:
        auto_trader_task.cancel()
    if scheduler is not None:
        scheduler.shutdown()
    logger.info("InfoHub shut down")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="InfoHub",
        description="Local multi-domain information aggregation system",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(items_router)
    app.include_router(domains_router)
    app.include_router(pipeline_router)
    app.include_router(daily_router)
    app.include_router(stats_router)
    app.include_router(sources_router)
    app.include_router(data_router)
    app.include_router(trading_router)

    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        index_file = FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"message": "InfoHub API is running."})

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal server error: {type(exc).__name__}"},
        )

    return app
