"""Health check endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.yaml_config import app_config

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    app: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=app_config.app.version,
        app=app_config.app.name,
    )
