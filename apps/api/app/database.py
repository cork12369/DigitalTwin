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
    ensure_compatibility_columns()


def ensure_compatibility_columns() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    _ensure_columns(
        inspector,
        table_names,
        "participant_tokens",
        {
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
            "active_experiment_variant_id": "VARCHAR(36)",
            "dynamic_flow_modifiers": "JSON",
            "calibration_band": "VARCHAR(40) NOT NULL DEFAULT 'unmeasured'",
            "calibration_ece": "FLOAT",
            "calibration_temperature": "FLOAT NOT NULL DEFAULT 1.0",
            "session_started_at": "TIMESTAMP",
            "session_time_budget_seconds": "INTEGER NOT NULL DEFAULT 3600",
            "session_abort_reason": "VARCHAR(80)",
            "briefing_acknowledged_at": "TIMESTAMP",
        },
    )
    _ensure_columns(
        inspector,
        table_names,
        "raw_events",
        {
            "holdout_slot": "BOOLEAN NOT NULL DEFAULT FALSE",
            "holdout_partition": "VARCHAR(40)",
            "answer_mode": "VARCHAR(20) NOT NULL DEFAULT 'binary'",
        },
    )
    _ensure_columns(
        inspector,
        table_names,
        "memory_cards",
        {
            "card_type": "VARCHAR(20) NOT NULL DEFAULT 'disposition'",
            "seed_source": "VARCHAR(40) NOT NULL DEFAULT 'compaction'",
            "promoted_at": "TIMESTAMP",
            "reinforcement_count": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        inspector,
        table_names,
        "memory_card_pillar_links",
        {
            "source_event_id": "VARCHAR(36)",
            "cumulative_delta_w": "FLOAT NOT NULL DEFAULT 0.0",
            "update_count": "INTEGER NOT NULL DEFAULT 0",
            "last_updated_at": "TIMESTAMP",
        },
    )


def _ensure_columns(inspector, table_names: set[str], table_name: str, column_definitions: dict[str, str]) -> None:
    if table_name not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing_columns = [(name, column_type) for name, column_type in column_definitions.items() if name not in existing_columns]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for column_name, column_type in missing_columns:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
