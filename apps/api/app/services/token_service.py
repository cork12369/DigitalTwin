import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ParticipantSession, ParticipantToken, SessionStatus, TokenStatus, now_utc


def generate_raw_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    settings = get_settings()
    return hashlib.sha256(f"{settings.app_secret_key}:{raw_token}".encode("utf-8")).hexdigest()


def create_participant_token(db: Session, label: str, expires_at: datetime | None = None) -> tuple[ParticipantToken, str]:
    raw_token = generate_raw_token()
    participant = ParticipantToken(label=label, token_hash=hash_token(raw_token), auth_key=raw_token, expires_at=expires_at)
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant, raw_token


def find_by_raw_token(db: Session, raw_token: str) -> ParticipantToken | None:
    return db.query(ParticipantToken).filter(ParticipantToken.token_hash == hash_token(raw_token)).first()


def is_expired(participant: ParticipantToken) -> bool:
    return participant.expires_at is not None and participant.expires_at <= datetime.now(timezone.utc)


def validate_and_touch_token(db: Session, raw_token: str) -> tuple[ParticipantToken | None, str]:
    participant = find_by_raw_token(db, raw_token)
    if participant is None:
        return None, "Token not found."
    if participant.status == TokenStatus.revoked:
        return participant, "Token has been revoked."
    if is_expired(participant):
        participant.status = TokenStatus.expired
        db.commit()
        return participant, "Token has expired."

    now = now_utc()
    if participant.first_used_at is None:
        participant.first_used_at = now
    participant.last_seen_at = now
    if participant.status in {TokenStatus.generated, TokenStatus.active, TokenStatus.reset}:
        participant.status = TokenStatus.in_progress
    db.commit()
    db.refresh(participant)
    return participant, "Token is valid."


def get_or_create_session(db: Session, participant: ParticipantToken) -> ParticipantSession:
    session = (
        db.query(ParticipantSession)
        .filter(ParticipantSession.token_id == participant.id, ParticipantSession.status != SessionStatus.completed)
        .order_by(ParticipantSession.created_at.desc())
        .first()
    )
    if session is None:
        session = ParticipantSession(token_id=participant.id, status=SessionStatus.in_progress)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session
