"""API v1 router aggregating all sub-routers."""

from fastapi import APIRouter

from app.api.v1.backtest import router as backtest_router
from app.api.v1.bot import router as bot_router
from app.api.v1.config import router as config_router
from app.api.v1.health import router as health_router
from app.api.v1.intelligence import router as intelligence_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.markets import router as markets_router
from app.monitoring.dashboard import router as dashboard_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router, tags=["health"])
api_v1_router.include_router(markets_router, tags=["markets"])
api_v1_router.include_router(knowledge_router, tags=["knowledge"])
api_v1_router.include_router(intelligence_router, tags=["intelligence"])
api_v1_router.include_router(bot_router, tags=["bot"])
api_v1_router.include_router(config_router)
api_v1_router.include_router(backtest_router)
api_v1_router.include_router(dashboard_router)
