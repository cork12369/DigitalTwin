from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ParticipantSession, ParticipantToken, RawEvent, SessionStatus, TokenStatus
from app.scenario import (
    MAX_ADAPTIVE_QUESTIONS,
    ONBOARDING_STEP,
    event_type_for_step,
    fallback_step,
    get_token_step,
    initial_adaptive_state,
    scenario_steps_for_token,
)
from app.schemas import (
    EventCreateRequest,
    EventResponse,
    SessionCompleteRequest,
    SessionStartRequest,
    SessionStateResponse,
    StepAnswerRequest,
    StepAnswerResponse,
)
from app.services.adaptive_scenario_service import (
    AdaptiveGenerationResult,
    generate_adaptive_step,
    initialize_generation_metadata,
)
from app.services.profile_service import ProfileIngestionResult, build_manual_profile, ingest_cv_pdf
from app.services.token_service import find_by_raw_token, get_or_create_session, validate_and_touch_token

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("/events", response_model=EventResponse)
def create_event(payload: EventCreateRequest, db: Session = Depends(get_db)) -> RawEvent:
    participant = find_by_raw_token(db, payload.token)
    if participant is None:
        raise HTTPException(status_code=404, detail="Token not found")

    session = get_or_create_session(db, participant)
    event = RawEvent(
        token_id=participant.id,
        session_id=payload.session_id or session.id,
        event_type=payload.event_type,
        payload=payload.payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.post("/start", response_model=SessionStateResponse)
def start_session(payload: SessionStartRequest, db: Session = Depends(get_db)) -> SessionStateResponse:
    participant, message = validate_and_touch_token(db, payload.token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail=message)

    session = get_or_create_session(db, participant)
    if session.status != SessionStatus.completed:
        session.status = SessionStatus.in_progress
    _ensure_session_current_step(db, participant, session)
    db.commit()
    db.refresh(session)
    return _session_state(db, session)


@router.get("/{session_id}/state", response_model=SessionStateResponse)
def get_session_state(session_id: str, db: Session = Depends(get_db)) -> SessionStateResponse:
    session = db.get(ParticipantSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_state(db, session)


@router.post("/{session_id}/profile/cv", response_model=StepAnswerResponse)
async def upload_cv_profile(
    session_id: str,
    token: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> StepAnswerResponse:
    participant, session = _participant_session_for_current_step(db, token, session_id, ONBOARDING_STEP["id"])
    try:
        file_bytes = await file.read()
        ingestion = ingest_cv_pdf(file.filename, file.content_type, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()

    event = _apply_profile_ingestion(
        db=db,
        participant=participant,
        session=session,
        step=ONBOARDING_STEP,
        ingestion=ingestion,
        answer={
            "profile_source_type": ingestion.source_type,
            "profile_source_filename": ingestion.source_filename,
            "user_profile": ingestion.user_profile,
        },
    )

    return StepAnswerResponse(
        event=event,
        current_step=session.current_step,
        next_step_id=None if session.current_step == "complete" else session.current_step,
        completed_step_ids=_completed_step_ids(db, session.id),
        is_ready_to_complete=session.current_step == "complete",
    )


@router.post("/{session_id}/answer", response_model=StepAnswerResponse)
def answer_step(session_id: str, payload: StepAnswerRequest, db: Session = Depends(get_db)) -> StepAnswerResponse:
    participant = find_by_raw_token(db, payload.token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail="Token is invalid or unavailable")

    session = db.get(ParticipantSession, session_id)
    if session is None or session.token_id != participant.id:
        raise HTTPException(status_code=404, detail="Session not found for token")
    if session.status == SessionStatus.completed or session.current_step == "complete":
        raise HTTPException(status_code=400, detail="Scenario is already complete")
    if payload.step_id != session.current_step:
        raise HTTPException(status_code=409, detail="Submitted step is not the current scenario step")

    step = get_token_step(_adaptive_steps(participant), payload.step_id)
    if step is None:
        raise HTTPException(status_code=400, detail="Unknown scenario step")
    if step["type"] != payload.step_type:
        raise HTTPException(status_code=400, detail="Step type does not match scenario definition")

    if step["type"] == "onboarding":
        event = _answer_onboarding(db, participant, session, step, payload.answer)
    else:
        event = _answer_adaptive_question(db, participant, session, step, payload.answer)

    return StepAnswerResponse(
        event=event,
        current_step=session.current_step,
        next_step_id=None if session.current_step == "complete" else session.current_step,
        completed_step_ids=_completed_step_ids(db, session.id),
        is_ready_to_complete=session.current_step == "complete",
    )


@router.post("/{session_id}/complete", response_model=SessionStateResponse)
def complete_session(session_id: str, payload: SessionCompleteRequest, db: Session = Depends(get_db)) -> SessionStateResponse:
    participant = find_by_raw_token(db, payload.token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail="Token is invalid or unavailable")

    session = db.get(ParticipantSession, session_id)
    if session is None or session.token_id != participant.id:
        raise HTTPException(status_code=404, detail="Session not found for token")
    if session.current_step != "complete" and session.status != SessionStatus.completed:
        raise HTTPException(status_code=400, detail="Adaptive scenario is not complete yet")

    if session.status != SessionStatus.completed:
        _mark_completed(db, participant, session, _session_events(db, session.id))
        db.commit()
        db.refresh(session)
    return _session_state(db, session)


def _answer_onboarding(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    step: dict[str, Any],
    answer: dict[str, Any],
) -> RawEvent:
    profile = _profile_text(answer)
    ingestion = build_manual_profile(profile)
    return _apply_profile_ingestion(
        db=db,
        participant=participant,
        session=session,
        step=step,
        ingestion=ingestion,
        answer={"user_profile": profile, "profile_source_type": ingestion.source_type},
    )


def _apply_profile_ingestion(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    step: dict[str, Any],
    ingestion: ProfileIngestionResult,
    answer: dict[str, Any],
) -> RawEvent:
    participant.user_profile = ingestion.user_profile
    participant.profile_source_type = ingestion.source_type
    participant.profile_source_filename = ingestion.source_filename
    participant.profile_structured_context = ingestion.structured_context
    participant.profile_llm_summary = ingestion.llm_summary
    participant.profile_ingestion_metadata = ingestion.metadata
    participant.adaptive_scenario_steps = []
    participant.adaptive_scenario_state = initial_adaptive_state()
    participant.scenario_generation_metadata = initialize_generation_metadata()

    event = _create_step_event(db, participant, session, step, answer)
    participant.status = TokenStatus.in_progress
    session.status = SessionStatus.in_progress
    db.commit()
    db.refresh(event)

    result = generate_adaptive_step(
        participant=participant,
        events=_session_events(db, session.id),
        last_step=None,
        last_answer=None,
        adaptive_answer_count=0,
    )
    _apply_generation_result(participant, result)
    if result.next_step is None:
        next_step = fallback_step(1)
        _append_adaptive_step(participant, next_step)
        session.current_step = next_step["id"]
    else:
        _append_adaptive_step(participant, result.next_step)
        session.current_step = result.next_step["id"]
    db.commit()
    db.refresh(event)
    db.refresh(session)
    return event


def _answer_adaptive_question(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    step: dict[str, Any],
    answer: dict[str, Any],
) -> RawEvent:
    normalized_answer = _choice_answer(step, answer)
    event = _create_step_event(db, participant, session, step, normalized_answer)
    participant.status = TokenStatus.in_progress
    session.status = SessionStatus.in_progress
    db.commit()
    db.refresh(event)

    events = _session_events(db, session.id)
    adaptive_answer_count = _adaptive_answer_count(events)
    result = generate_adaptive_step(
        participant=participant,
        events=events,
        last_step=step,
        last_answer=normalized_answer,
        adaptive_answer_count=adaptive_answer_count,
    )
    _apply_generation_result(participant, result)

    if result.should_complete:
        _mark_completed(db, participant, session, events)
    else:
        next_step = result.next_step or fallback_step(adaptive_answer_count + 1)
        _append_adaptive_step(participant, next_step)
        session.current_step = next_step["id"]

    db.commit()
    db.refresh(event)
    db.refresh(session)
    return event


def _create_step_event(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    step: dict[str, Any],
    answer: dict[str, Any],
) -> RawEvent:
    event = RawEvent(
        token_id=participant.id,
        session_id=session.id,
        event_type=event_type_for_step(step["type"]),
        payload={
            "step_id": step["id"],
            "step_type": step["type"],
            "answer": answer,
            "step_snapshot": step,
        },
    )
    db.add(event)
    return event


def _participant_session_for_current_step(
    db: Session,
    raw_token: str,
    session_id: str,
    expected_step_id: str,
) -> tuple[ParticipantToken, ParticipantSession]:
    participant = find_by_raw_token(db, raw_token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail="Token is invalid or unavailable")

    session = db.get(ParticipantSession, session_id)
    if session is None or session.token_id != participant.id:
        raise HTTPException(status_code=404, detail="Session not found for token")
    if session.status == SessionStatus.completed or session.current_step == "complete":
        raise HTTPException(status_code=400, detail="Scenario is already complete")
    if session.current_step != expected_step_id:
        raise HTTPException(status_code=409, detail="CV upload is only available during profile setup")

    return participant, session


def _ensure_session_current_step(db: Session, participant: ParticipantToken, session: ParticipantSession) -> None:
    if session.status == SessionStatus.completed or participant.status == TokenStatus.completed:
        session.current_step = "complete"
        return

    if not participant.user_profile:
        session.current_step = ONBOARDING_STEP["id"]
        return

    events = _session_events(db, session.id)
    steps = _adaptive_steps(participant)
    completed = set(_completed_step_ids_from_events(events))
    for step in steps:
        if step.get("id") not in completed:
            session.current_step = str(step["id"])
            return

    adaptive_count = _adaptive_answer_count(events)
    if adaptive_count >= MAX_ADAPTIVE_QUESTIONS:
        _mark_completed(db, participant, session, events)
        return

    result = generate_adaptive_step(
        participant=participant,
        events=events,
        last_step=None,
        last_answer=None,
        adaptive_answer_count=adaptive_count,
    )
    _apply_generation_result(participant, result)
    if result.should_complete:
        _mark_completed(db, participant, session, events)
        return

    next_step = result.next_step or fallback_step(adaptive_count + 1)
    _append_adaptive_step(participant, next_step)
    session.current_step = next_step["id"]


def _session_state(db: Session, session: ParticipantSession) -> SessionStateResponse:
    token = session.token
    events = _session_events(db, session.id)
    metadata = token.scenario_generation_metadata or {}
    return SessionStateResponse(
        session_id=session.id,
        token_id=session.token_id,
        token_status=token.status,
        session_status=session.status,
        current_step=session.current_step,
        steps=scenario_steps_for_token(_adaptive_steps(token)),
        completed_step_ids=_completed_step_ids_from_events(events),
        event_count=len(events),
        adaptive_question_count=_adaptive_answer_count(events),
        max_adaptive_questions=MAX_ADAPTIVE_QUESTIONS,
        scenario_generation_status=metadata.get("status"),
        scenario_generation_message=metadata.get("reason"),
    )


def _mark_completed(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    events: list[RawEvent],
) -> None:
    completed_step_ids = _completed_step_ids_from_events(events)
    already_completed = any(event.event_type == "scenario_completed" for event in events)
    if not already_completed:
        db.add(
            RawEvent(
                token_id=participant.id,
                session_id=session.id,
                event_type="scenario_completed",
                payload={
                    "step_id": "complete",
                    "completed_step_ids": completed_step_ids,
                    "adaptive_question_count": _adaptive_answer_count(events),
                    "confidence": (participant.adaptive_scenario_state or {}).get("confidence"),
                },
            )
        )
    session.status = SessionStatus.completed
    session.current_step = "complete"
    participant.status = TokenStatus.completed
    participant.completed_at = datetime.now(timezone.utc)


def _apply_generation_result(participant: ParticipantToken, result: AdaptiveGenerationResult) -> None:
    participant.adaptive_scenario_state = dict(result.hidden_state)
    existing_metadata = dict(participant.scenario_generation_metadata or {})
    history = list(existing_metadata.get("history") or [])
    history.append(result.metadata)
    existing_metadata.update(result.metadata)
    existing_metadata["history"] = history[-8:]
    participant.scenario_generation_metadata = existing_metadata


def _append_adaptive_step(participant: ParticipantToken, step: dict[str, Any]) -> None:
    steps = _adaptive_steps(participant)
    if not any(existing.get("id") == step.get("id") for existing in steps):
        steps.append(step)
    participant.adaptive_scenario_steps = steps


def _profile_text(answer: dict[str, Any]) -> str:
    value = answer.get("user_profile") or answer.get("text")
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="Profile text is required")
    profile = value.strip()
    if len(profile) < 2:
        raise HTTPException(status_code=400, detail="Profile text is too short")
    if len(profile) > 2000:
        raise HTTPException(status_code=400, detail="Profile text must be 2000 characters or fewer")
    return profile


def _choice_answer(step: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    selected_index = answer.get("selected_index")
    if type(selected_index) is not int:
        raise HTTPException(status_code=400, detail="selected_index is required")

    options = step.get("options") or []
    if selected_index < 0 or selected_index >= len(options):
        raise HTTPException(status_code=400, detail="selected_index is outside the available options")

    selected_option = answer.get("selected_option")
    expected_option = options[selected_index]
    if selected_option != expected_option:
        raise HTTPException(status_code=400, detail="selected_option does not match selected_index")

    return {
        "selected_index": selected_index,
        "selected_option": expected_option,
    }


def _session_events(db: Session, session_id: str) -> list[RawEvent]:
    return db.query(RawEvent).filter(RawEvent.session_id == session_id).order_by(RawEvent.created_at.asc()).all()


def _completed_step_ids(db: Session, session_id: str) -> list[str]:
    return _completed_step_ids_from_events(_session_events(db, session_id))


def _completed_step_ids_from_events(events: list[RawEvent]) -> list[str]:
    return [
        event.payload.get("step_id")
        for event in events
        if isinstance(event.payload, dict)
        and event.event_type != "scenario_completed"
        and event.payload.get("step_id")
    ]


def _adaptive_answer_count(events: list[RawEvent]) -> int:
    return sum(
        1
        for event in events
        if isinstance(event.payload, dict)
        and event.payload.get("step_type") in {"triad", "duel"}
        and str(event.payload.get("step_id", "")).startswith("adaptive_q_")
    )


def _adaptive_steps(participant: ParticipantToken) -> list[dict[str, Any]]:
    value = participant.adaptive_scenario_steps
    return list(value) if isinstance(value, list) else []
