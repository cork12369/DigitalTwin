from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

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
    return {
        "status": "placeholder",
        "langchain": "not_configured_yet",
        "message": "LangChain workflow layer will be enabled in a later phase.",
    }