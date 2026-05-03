"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.dependencies import (
    get_bot_service,
    start_intelligence_scheduler,
    stop_intelligence_scheduler,
)
from app.core.logging import get_logger, setup_logging
from app.core.yaml_config import app_config

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown.

    Auto-starts the trading bot loop when ``app_config.bot.auto_start`` is True
    so the execution engine (and the snapshot writer that ticks inside it) run
    without requiring an explicit ``POST /api/v1/bot/start`` call.
    """
    setup_logging(log_level=settings.log_level)
    logger.info(
        "starting",
        app=app_config.app.name,
        version=app_config.app.version,
        env=settings.app_env,
        dry_run=settings.dry_run,
    )

    bot = None
    if app_config.bot.auto_start:
        bot = await get_bot_service()
        await bot.start(interval_seconds=app_config.bot.tick_interval_seconds)
        logger.info(
            "bot_auto_started",
            interval=app_config.bot.tick_interval_seconds,
        )
    else:
        logger.info("bot_auto_start_skipped", reason="config disabled")

    try:
        await start_intelligence_scheduler()
    except Exception as exc:
        logger.warning("intelligence_scheduler_start_failed", error=str(exc))

    try:
        yield
    finally:
        if bot is not None:
            await bot.stop()
        try:
            await stop_intelligence_scheduler()
        except Exception as exc:
            logger.debug("intelligence_scheduler_stop_failed", error=str(exc))
        logger.info("shutting_down")


app = FastAPI(
    title="PolymarketBot",
    version=app_config.app.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/")
async def root_redirect() -> RedirectResponse:
    """Redirect root to dashboard for local dev convenience."""
    return RedirectResponse(url="/static/index.html")


# Mount static files for dashboard
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
