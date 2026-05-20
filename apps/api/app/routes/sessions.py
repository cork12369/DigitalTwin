from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ParticipantSession, RawEvent, SessionStatus, TokenStatus
from app.scenario import SCENARIO_STEPS, event_type_for_step, get_next_step_id, get_step
from app.schemas import (
    EventCreateRequest,
    EventResponse,
    SessionCompleteRequest,
    SessionStartRequest,
    SessionStateResponse,
    StepAnswerRequest,
    StepAnswerResponse,
)
from app.services.token_service import find_by_raw_token, get_or_create_session, validate_and_touch_token

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _answer_text(answer: dict, key: str) -> str | None:
    value = answer.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _sentence(value: str) -> str:
    return value.strip().rstrip(".")


def _preliminary_twin_read(events: list[RawEvent]) -> list[str]:
    answers_by_step = {
        event.payload.get("step_id"): event.payload.get("answer", {})
        for event in events
        if isinstance(event.payload, dict)
    }

    triad_1 = _answer_text(answers_by_step.get("triad_1", {}), "selected_option")
    triad_2 = _answer_text(answers_by_step.get("triad_2", {}), "selected_option")
    triad_3 = _answer_text(answers_by_step.get("triad_3", {}), "selected_option")
    duel_1 = _answer_text(answers_by_step.get("duel_1", {}), "selected_option")
    duel_2 = _answer_text(answers_by_step.get("duel_2", {}), "selected_option")
    duel_3 = _answer_text(answers_by_step.get("duel_3", {}), "selected_option")
    context_1 = _answer_text(answers_by_step.get("context_flip_1", {}), "text")
    context_2 = _answer_text(answers_by_step.get("context_flip_2", {}), "text")
    ranked = answers_by_step.get("twin_rank_1", {}).get("ranked_options", [])

    read: list[str] = []
    if triad_1 or triad_2 or triad_3:
        read.append(
            "Under pressure, the twin currently reads your first-pass priorities as: "
            + ", ".join(option for option in [triad_1, triad_2, triad_3] if option)
            + "."
        )
    if duel_1 or duel_2:
        read.append(
            "In trade-offs, it currently assumes you lean toward "
            + " and ".join(option for option in [duel_1, duel_2] if option)
            + "."
        )
    if duel_3:
        read.append(f"For disagreement with the twin, it currently believes you prefer: {duel_3}.")
    if context_1 or context_2:
        read.append(
            "Your context-flip answers suggest these choices may change by audience, reversibility, or public visibility."
        )
    if isinstance(ranked, list) and ranked:
        read.append(f"The response it treats as closest to you is: {_sentence(str(ranked[0]))}.")

    return read or ["The twin has not collected enough answers yet to form a useful preliminary read."]


def _steps_for_session(events: list[RawEvent]) -> list[dict]:
    twin_read = _preliminary_twin_read(events)
    steps: list[dict] = []
    for step in SCENARIO_STEPS:
        if step["id"] == "correction_1":
            steps.append(
                {
                    **step,
                    "context_title": "Preliminary twin read",
                    "context_items": twin_read,
                }
            )
        else:
            steps.append(step)
    return steps


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


def _completed_step_ids(db: Session, session_id: str) -> list[str]:
    events = db.query(RawEvent).filter(RawEvent.session_id == session_id).order_by(RawEvent.created_at.asc()).all()
    return [event.payload.get("step_id") for event in events if event.payload.get("step_id")]


def _session_state(db: Session, session: ParticipantSession) -> SessionStateResponse:
    token = session.token
    events = db.query(RawEvent).filter(RawEvent.session_id == session.id).order_by(RawEvent.created_at.asc()).all()
    return SessionStateResponse(
        session_id=session.id,
        token_id=session.token_id,
        token_status=token.status,
        session_status=session.status,
        current_step=session.current_step,
        steps=_steps_for_session(events),
        completed_step_ids=[event.payload.get("step_id") for event in events if event.payload.get("step_id")],
        event_count=len(events),
    )


@router.post("/start", response_model=SessionStateResponse)
def start_session(payload: SessionStartRequest, db: Session = Depends(get_db)) -> SessionStateResponse:
    participant, message = validate_and_touch_token(db, payload.token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail=message)

    session = get_or_create_session(db, participant)
    if session.current_step == "intro":
        session.status = SessionStatus.in_progress
        db.commit()
        db.refresh(session)
    return _session_state(db, session)


@router.get("/{session_id}/state", response_model=SessionStateResponse)
def get_session_state(session_id: str, db: Session = Depends(get_db)) -> SessionStateResponse:
    session = db.get(ParticipantSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_state(db, session)


@router.post("/{session_id}/answer", response_model=StepAnswerResponse)
def answer_step(session_id: str, payload: StepAnswerRequest, db: Session = Depends(get_db)) -> StepAnswerResponse:
    participant = find_by_raw_token(db, payload.token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail="Token is invalid or unavailable")

    session = db.get(ParticipantSession, session_id)
    if session is None or session.token_id != participant.id:
        raise HTTPException(status_code=404, detail="Session not found for token")

    step = get_step(payload.step_id)
    if step is None:
        raise HTTPException(status_code=400, detail="Unknown scenario step")
    if step["type"] != payload.step_type:
        raise HTTPException(status_code=400, detail="Step type does not match scenario definition")

    event = RawEvent(
        token_id=participant.id,
        session_id=session.id,
        event_type=event_type_for_step(payload.step_type),
        payload={"step_id": payload.step_id, "step_type": payload.step_type, "answer": payload.answer},
    )
    db.add(event)

    next_step_id = get_next_step_id(payload.step_id)
    session.current_step = next_step_id or "complete"
    session.status = SessionStatus.in_progress
    participant.status = TokenStatus.in_progress
    db.commit()
    db.refresh(event)
    db.refresh(session)

    return StepAnswerResponse(
        event=event,
        current_step=session.current_step,
        next_step_id=next_step_id,
        completed_step_ids=_completed_step_ids(db, session.id),
        is_ready_to_complete=next_step_id is None,
    )


@router.post("/{session_id}/complete", response_model=SessionStateResponse)
def complete_session(session_id: str, payload: SessionCompleteRequest, db: Session = Depends(get_db)) -> SessionStateResponse:
    participant = find_by_raw_token(db, payload.token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail="Token is invalid or unavailable")

    session = db.get(ParticipantSession, session_id)
    if session is None or session.token_id != participant.id:
        raise HTTPException(status_code=404, detail="Session not found for token")

    completed_steps = set(_completed_step_ids(db, session.id))
    required_steps = {step["id"] for step in SCENARIO_STEPS}
    if not required_steps.issubset(completed_steps):
        raise HTTPException(status_code=400, detail="Scenario has incomplete required steps")

    event = RawEvent(
        token_id=participant.id,
        session_id=session.id,
        event_type="scenario_completed",
        payload={"step_id": "complete", "completed_step_ids": sorted(completed_steps)},
    )
    db.add(event)
    session.status = SessionStatus.completed
    session.current_step = "complete"
    participant.status = TokenStatus.completed
    participant.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return _session_state(db, session)
