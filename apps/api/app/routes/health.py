from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "digital-twin-api"}


@router.get("/health/db")
def database_health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}


@router.get("/health/langchain")
def langchain_health() -> dict:
    settings = get_settings()
    provider_status = "configured" if settings.has_openrouter_key else "not_configured"
    return {
        "status": "ok" if settings.has_openrouter_key else "placeholder",
        "langchain": "mock_orchestration_ready",
        "model_provider": "openrouter",
        "provider_status": provider_status,
        "model": settings.openrouter_model,
        "message": "OpenRouter is configured for LLM-backed review." if settings.has_openrouter_key else "OpenRouter key is not configured; analysis will use the local mock extractor.",
    }