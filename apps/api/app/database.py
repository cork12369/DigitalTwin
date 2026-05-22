from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_participant_token_columns()


def ensure_participant_token_columns() -> None:
    inspector = inspect(engine)
    if "participant_tokens" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("participant_tokens")}
    column_definitions = {
        "auth_key": "TEXT",
        "user_profile": "TEXT",
        "profile_source_type": "VARCHAR(40)",
        "profile_source_filename": "VARCHAR(255)",
        "profile_structured_context": "JSON",
        "profile_llm_summary": "JSON",
        "profile_ingestion_metadata": "JSON",
        "adaptive_scenario_steps": "JSON",
        "adaptive_scenario_state": "JSON",
        "scenario_generation_metadata": "JSON",
        "initialization_status": "VARCHAR(40) NOT NULL DEFAULT 'not_started'",
        "guide_persona": "JSON",
        "guide_custom_prompt": "TEXT",
        "memory_readiness_snapshot": "JSON",
    }
    missing_columns = [
        (name, column_type)
        for name, column_type in column_definitions.items()
        if name not in existing_columns
    ]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for column_name, column_type in missing_columns:
            connection.execute(text(f"ALTER TABLE participant_tokens ADD COLUMN {column_name} {column_type}"))
