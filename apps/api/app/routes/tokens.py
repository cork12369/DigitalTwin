from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import require_admin_secret
from app.models import (
    AnalysisRun,
    BehavioralEvidence,
    CoverageGraphSnapshot,
    MemoryCard,
    MemoryCardDuplicateSuggestion,
    MemoryCardPillarLink,
    MemoryCompactionRun,
    ParticipantSession,
    ParticipantToken,
    RawEvent,
    TokenStatus,
    TrainingChatMessage,
    TrainingChatSession,
    TwinHarnessRun,
)
from app.schemas import AdminTokenSummaryResponse, TokenCreateRequest, TokenCreateResponse, TokenResponse, TokenValidateRequest, TokenValidateResponse
from app.services.token_service import create_participant_token, get_or_create_session, validate_and_touch_token

router = APIRouter(prefix="/api", tags=["tokens"])
admin_router = APIRouter(prefix="/admin/tokens", tags=["tokens"], dependencies=[Depends(require_admin_secret)])


@admin_router.post("", response_model=TokenCreateResponse)
def create_token(payload: TokenCreateRequest, db: Session = Depends(get_db)) -> TokenCreateResponse:
    participant, raw_token = create_participant_token(db, label=payload.label, expires_at=payload.expires_at)
    invite_url = f"{get_settings().public_web_url.rstrip('/')}/play/{raw_token}"
    return TokenCreateResponse(token=raw_token, invite_url=invite_url, participant=participant)


@admin_router.get("", response_model=list[TokenResponse])
def list_tokens(db: Session = Depends(get_db)) -> list[ParticipantToken]:
    return db.query(ParticipantToken).order_by(ParticipantToken.created_at.desc()).all()


@admin_router.get("/summary", response_model=list[AdminTokenSummaryResponse])
def list_token_summaries(db: Session = Depends(get_db)) -> list[AdminTokenSummaryResponse]:
    participants = db.query(ParticipantToken).order_by(ParticipantToken.created_at.desc()).all()
    summaries: list[AdminTokenSummaryResponse] = []
    for participant in participants:
        session = (
            db.query(ParticipantSession)
            .filter(ParticipantSession.token_id == participant.id)
            .order_by(ParticipantSession.created_at.desc())
            .first()
        )
        event_count = db.query(RawEvent).filter(RawEvent.token_id == participant.id).count()
        latest_analysis = (
            db.query(AnalysisRun)
            .filter(AnalysisRun.token_id == participant.id)
            .order_by(AnalysisRun.created_at.desc())
            .first()
        )
        evidence_count = db.query(BehavioralEvidence).filter(BehavioralEvidence.token_id == participant.id).count()
        summaries.append(
            AdminTokenSummaryResponse.model_validate(participant).model_copy(
                update={
                    "current_step": session.current_step if session else None,
                    "session_status": session.status if session else None,
                    "event_count": event_count,
                    "latest_analysis_status": latest_analysis.status if latest_analysis else None,
                    "evidence_count": evidence_count,
                    "invite_url": (
                        f"{get_settings().public_web_url.rstrip('/')}/play/{participant.auth_key}"
                        if participant.auth_key else None
                    ),
                }
            )
        )
    return summaries


@admin_router.post("/{token_id}/revoke", response_model=TokenResponse)
def revoke_token(token_id: str, db: Session = Depends(get_db)) -> ParticipantToken:
    participant = db.get(ParticipantToken, token_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Token not found")
    participant.status = TokenStatus.revoked
    db.commit()
    db.refresh(participant)
    return participant


@admin_router.post("/{token_id}/reset", response_model=TokenResponse)
def reset_token(token_id: str, db: Session = Depends(get_db)) -> ParticipantToken:
    participant = db.get(ParticipantToken, token_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Token not found")
    for run in db.query(TwinHarnessRun).filter(TwinHarnessRun.token_id == participant.id).all():
        db.delete(run)
    for run in db.query(AnalysisRun).filter(AnalysisRun.token_id == participant.id).all():
        db.delete(run)
    for event in db.query(RawEvent).filter(RawEvent.token_id == participant.id).all():
        db.delete(event)
    for session in db.query(ParticipantSession).filter(ParticipantSession.token_id == participant.id).all():
        db.delete(session)
    for suggestion in db.query(MemoryCardDuplicateSuggestion).filter(MemoryCardDuplicateSuggestion.token_id == participant.id).all():
        db.delete(suggestion)
    card_ids = [card.id for card in db.query(MemoryCard).filter(MemoryCard.token_id == participant.id).all()]
    if card_ids:
        for link in db.query(MemoryCardPillarLink).filter(MemoryCardPillarLink.card_id.in_(card_ids)).all():
            db.delete(link)
    for card in db.query(MemoryCard).filter(MemoryCard.token_id == participant.id).all():
        db.delete(card)
    for run in db.query(MemoryCompactionRun).filter(MemoryCompactionRun.token_id == participant.id).all():
        db.delete(run)
    for message in db.query(TrainingChatMessage).filter(TrainingChatMessage.token_id == participant.id).all():
        db.delete(message)
    for chat in db.query(TrainingChatSession).filter(TrainingChatSession.token_id == participant.id).all():
        db.delete(chat)
    for snapshot in db.query(CoverageGraphSnapshot).filter(CoverageGraphSnapshot.token_id == participant.id).all():
        db.delete(snapshot)
    participant.status = TokenStatus.reset
    participant.completed_at = None
    participant.user_profile = None
    participant.profile_source_type = None
    participant.profile_source_filename = None
    participant.profile_structured_context = {}
    participant.profile_llm_summary = None
    participant.profile_ingestion_metadata = {}
    participant.adaptive_scenario_steps = []
    participant.adaptive_scenario_state = {}
    participant.scenario_generation_metadata = {}
    participant.initialization_status = "not_started"
    participant.guide_persona = {}
    participant.guide_custom_prompt = None
    participant.memory_readiness_snapshot = {}
    db.commit()
    db.refresh(participant)
    return participant


@admin_router.delete("/{token_id}", status_code=204)
def delete_revoked_token(token_id: str, db: Session = Depends(get_db)) -> None:
    participant = db.get(ParticipantToken, token_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Token not found")
    if participant.status != TokenStatus.revoked:
        raise HTTPException(status_code=400, detail="Only revoked tokens can be deleted")

    for run in db.query(TwinHarnessRun).filter(TwinHarnessRun.token_id == participant.id).all():
        db.delete(run)
    for run in db.query(AnalysisRun).filter(AnalysisRun.token_id == participant.id).all():
        db.delete(run)
    for evidence in db.query(BehavioralEvidence).filter(BehavioralEvidence.token_id == participant.id).all():
        db.delete(evidence)
    for event in db.query(RawEvent).filter(RawEvent.token_id == participant.id).all():
        db.delete(event)
    for session in db.query(ParticipantSession).filter(ParticipantSession.token_id == participant.id).all():
        db.delete(session)
    for suggestion in db.query(MemoryCardDuplicateSuggestion).filter(MemoryCardDuplicateSuggestion.token_id == participant.id).all():
        db.delete(suggestion)
    card_ids = [card.id for card in db.query(MemoryCard).filter(MemoryCard.token_id == participant.id).all()]
    if card_ids:
        for link in db.query(MemoryCardPillarLink).filter(MemoryCardPillarLink.card_id.in_(card_ids)).all():
            db.delete(link)
    for card in db.query(MemoryCard).filter(MemoryCard.token_id == participant.id).all():
        db.delete(card)
    for run in db.query(MemoryCompactionRun).filter(MemoryCompactionRun.token_id == participant.id).all():
        db.delete(run)
    for message in db.query(TrainingChatMessage).filter(TrainingChatMessage.token_id == participant.id).all():
        db.delete(message)
    for chat in db.query(TrainingChatSession).filter(TrainingChatSession.token_id == participant.id).all():
        db.delete(chat)
    for snapshot in db.query(CoverageGraphSnapshot).filter(CoverageGraphSnapshot.token_id == participant.id).all():
        db.delete(snapshot)
    db.delete(participant)
    db.commit()


@router.post("/tokens/validate", response_model=TokenValidateResponse)
def validate_token(payload: TokenValidateRequest, db: Session = Depends(get_db)) -> TokenValidateResponse:
    participant, message = validate_and_touch_token(db, payload.token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        return TokenValidateResponse(valid=False, status=participant.status if participant else None, message=message)

    session = get_or_create_session(db, participant)
    return TokenValidateResponse(
        valid=True,
        participant_id=participant.id,
        status=participant.status,
        session_id=session.id,
        message=message,
    )


router.include_router(admin_router)
