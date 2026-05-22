from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin_secret
from app.models import CoverageGraphSnapshot, MemoryCard, MemoryCardDuplicateSuggestion, MemoryCompactionRun, ParticipantToken, TokenStatus, TrainingChatMessage
from app.schemas import (
    GuideSettingsUpdateRequest,
    MemoryCardDeleteRequest,
    MemoryCardDuplicateSuggestionResponse,
    MemoryCardPillarLinkResponse,
    MemoryCardResponse,
    MemoryCardsListRequest,
    MemoryCardsResponse,
    MemoryCardUpdateRequest,
    TrainingDiagnosticsResponse,
    TrainingMessageCreateRequest,
    TrainingStartRequest,
    TrainingStateResponse,
)
from app.services.token_service import validate_and_touch_token
from app.services.harness_service import queue_harness_run, run_harness_job
from app.services.openviking_service import queue_openviking_sync, run_openviking_sync_job
from app.services.training_service import (
    PAIR_BLOCK_SIZE,
    PILLARS,
    PRIORITY_WEIGHTS,
    build_graph_diagnostics,
    build_readiness,
    create_user_assistant_exchange,
    delete_card,
    ensure_training_available,
    get_or_create_training_chat,
    run_compaction_job,
    snapshot_coverage,
    update_card,
)

router = APIRouter(prefix="/api/training", tags=["training"])
admin_router = APIRouter(prefix="/api/admin", tags=["training-admin"], dependencies=[Depends(require_admin_secret)])


@router.post("/start", response_model=TrainingStateResponse)
def start_training(payload: TrainingStartRequest, db: Session = Depends(get_db)) -> TrainingStateResponse:
    participant = _participant_for_training_token(db, payload.token)
    chat = get_or_create_training_chat(db, participant)
    return _training_state(db, participant, chat.id)


@router.post("/{chat_session_id}/messages", response_model=TrainingStateResponse)
def send_training_message(
    chat_session_id: str,
    payload: TrainingMessageCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TrainingStateResponse:
    participant = _participant_for_training_token(db, payload.token)
    chat = get_or_create_training_chat(db, participant)
    if chat.id != chat_session_id:
        raise HTTPException(status_code=409, detail="Training chat session does not match current active session")
    try:
        _, _, compaction_run = create_user_assistant_exchange(db, participant, chat, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if compaction_run is not None:
        background_tasks.add_task(run_compaction_job, compaction_run.id)
    return _training_state(
        db,
        participant,
        chat.id,
        compaction_notice="Memory cards are being drafted from the latest chat block." if compaction_run else None,
    )


@router.post("/settings", response_model=TrainingStateResponse)
def update_guide_settings(payload: GuideSettingsUpdateRequest, db: Session = Depends(get_db)) -> TrainingStateResponse:
    participant = _participant_for_training_token(db, payload.token)
    chat = get_or_create_training_chat(db, participant)
    participant.guide_custom_prompt = (payload.custom_prompt or "").strip()[:1200] or None
    db.commit()
    db.refresh(participant)
    return _training_state(db, participant, chat.id)


@router.post("/cards", response_model=MemoryCardsResponse)
def list_memory_cards(payload: MemoryCardsListRequest, db: Session = Depends(get_db)) -> MemoryCardsResponse:
    participant = _participant_for_training_token(db, payload.token)
    return _cards_response(db, participant)


@router.patch("/cards/{card_id}", response_model=MemoryCardsResponse)
def update_memory_card(
    card_id: str,
    payload: MemoryCardUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MemoryCardsResponse:
    participant = _participant_for_training_token(db, payload.token)
    card = db.get(MemoryCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Memory card not found")
    try:
        update_card(
            db=db,
            participant=participant,
            card=card,
            title=payload.title,
            body=payload.body,
            status=payload.status,
            priority=payload.priority,
            pillar_keys=payload.pillar_keys,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _queue_harness_background(db, participant, background_tasks, "memory_card_updated")
    return _cards_response(db, participant)


@router.post("/cards/{card_id}/delete", response_model=MemoryCardsResponse)
def delete_memory_card(
    card_id: str,
    payload: MemoryCardDeleteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MemoryCardsResponse:
    participant = _participant_for_training_token(db, payload.token)
    card = db.get(MemoryCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Memory card not found")
    try:
        delete_card(db, participant, card)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _queue_harness_background(db, participant, background_tasks, "memory_card_deleted")
    return _cards_response(db, participant)


@admin_router.get("/tokens/{token_id}/training-diagnostics", response_model=TrainingDiagnosticsResponse)
def get_training_diagnostics(token_id: str, db: Session = Depends(get_db)) -> TrainingDiagnosticsResponse:
    participant = db.get(ParticipantToken, token_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Token not found")
    readiness = build_readiness(db, participant, persist=True)
    graph = build_graph_diagnostics(db, participant)
    latest_snapshot = (
        db.query(CoverageGraphSnapshot)
        .filter(CoverageGraphSnapshot.token_id == token_id)
        .order_by(CoverageGraphSnapshot.created_at.desc())
        .first()
    )
    db.add(snapshot_coverage(db, participant, "admin_diagnostics_view", readiness))
    db.commit()
    return TrainingDiagnosticsResponse(
        token_id=token_id,
        readiness=readiness,
        graph=graph,
        latest_snapshot=latest_snapshot.payload if latest_snapshot else None,
    )


def _participant_for_training_token(db: Session, raw_token: str) -> ParticipantToken:
    participant, message = validate_and_touch_token(db, raw_token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail=message)
    try:
        ensure_training_available(participant)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return participant


def _training_state(
    db: Session,
    participant: ParticipantToken,
    chat_session_id: str,
    compaction_notice: str | None = None,
) -> TrainingStateResponse:
    chat = get_or_create_training_chat(db, participant)
    if chat.id != chat_session_id:
        chat_session_id = chat.id
    readiness = build_readiness(db, participant, persist=True)
    latest_run = (
        db.query(MemoryCompactionRun)
        .filter(MemoryCompactionRun.token_id == participant.id)
        .order_by(MemoryCompactionRun.created_at.desc())
        .first()
    )
    messages = (
        db.query(TrainingChatMessage)
        .filter(TrainingChatMessage.chat_session_id == chat.id)
        .order_by(TrainingChatMessage.message_index.asc())
        .all()
    )
    db.commit()
    db.refresh(chat)
    return TrainingStateResponse(
        token_id=participant.id,
        chat_session_id=chat.id,
        initialization_status=participant.initialization_status,
        guide_custom_prompt=participant.guide_custom_prompt,
        messages=messages,
        readiness=readiness,
        pair_count=chat.pair_count,
        pair_block_size=PAIR_BLOCK_SIZE,
        draft_card_count=int(readiness.get("draft_card_count", 0)),
        latest_compaction_run_id=latest_run.id if latest_run else None,
        latest_compaction_status=latest_run.status if latest_run else None,
        compaction_notice=compaction_notice,
    )


def _queue_harness_background(
    db: Session,
    participant: ParticipantToken,
    background_tasks: BackgroundTasks,
    trigger_reason: str,
) -> None:
    run = queue_harness_run(db, participant, trigger_reason)
    if run is not None:
        background_tasks.add_task(run_harness_job, run.id)
    sync_run = queue_openviking_sync(db, participant, trigger_reason)
    if sync_run is not None:
        background_tasks.add_task(run_openviking_sync_job, sync_run.id)


def _cards_response(db: Session, participant: ParticipantToken) -> MemoryCardsResponse:
    readiness = build_readiness(db, participant, persist=True)
    db.commit()
    cards = (
        db.query(MemoryCard)
        .filter(MemoryCard.token_id == participant.id)
        .order_by(MemoryCard.status.asc(), MemoryCard.priority.asc(), MemoryCard.updated_at.desc())
        .all()
    )
    return MemoryCardsResponse(
        token_id=participant.id,
        pillars=PILLARS,
        priority_weights=PRIORITY_WEIGHTS,
        readiness=readiness,
        cards=[_card_response(db, card) for card in cards],
    )


def _card_response(db: Session, card: MemoryCard) -> MemoryCardResponse:
    duplicate_rows = (
        db.query(MemoryCardDuplicateSuggestion)
        .filter(MemoryCardDuplicateSuggestion.candidate_card_id == card.id, MemoryCardDuplicateSuggestion.status == "open")
        .order_by(MemoryCardDuplicateSuggestion.created_at.desc())
        .all()
    )
    matched_ids = {row.matched_card_id for row in duplicate_rows}
    matched_titles = {
        matched.id: matched.title
        for matched in db.query(MemoryCard).filter(MemoryCard.id.in_(matched_ids)).all()
    } if matched_ids else {}
    return MemoryCardResponse(
        id=card.id,
        title=card.title,
        body=card.body,
        status=card.status,
        priority=card.priority,
        source_quote=card.source_quote,
        pillar_links=[MemoryCardPillarLinkResponse(pillar_key=link.pillar_key, weight=link.weight) for link in card.pillar_links],
        duplicate_suggestions=[
            MemoryCardDuplicateSuggestionResponse.model_validate(row).model_copy(
                update={"matched_card_title": matched_titles.get(row.matched_card_id)}
            )
            for row in duplicate_rows
        ],
        created_at=card.created_at,
        updated_at=card.updated_at,
    )
