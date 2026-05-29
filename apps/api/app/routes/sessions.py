from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ParticipantSession, ParticipantToken, RawEvent, SessionStatus, TokenStatus
from app.scenario import (
    MAX_ADAPTIVE_QUESTIONS,
    MIN_REPLAY_START_QUESTIONS,
    ONBOARDING_STEP,
    REPLAY_SCENARIO_COUNT,
    TWIN_RESPONSES_PER_REPLAY,
    event_type_for_step,
    fallback_step,
    get_token_step,
    initial_adaptive_state,
    scenario_steps_for_token,
    should_complete,
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
    generate_context_flip_step,
    generate_twin_rank_step,
    initialize_generation_metadata,
    record_adaptive_choice_signal,
)
from app.services.harness_service import queue_harness_run, run_harness_job
from app.services.openviking_service import queue_openviking_sync, run_openviking_sync_job
from app.services.profile_service import ProfileIngestionResult, build_manual_profile, ingest_cv_pdf
from app.services.token_service import find_by_raw_token, get_or_create_session, validate_and_touch_token
from app.services.v2_lineage_service import finalize_calibration, queue_subagent_eval_for_event

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
def answer_step(
    session_id: str,
    payload: StepAnswerRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> StepAnswerResponse:
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
        event = _answer_generated_step(db, participant, session, step, payload.answer, payload.answer_mode)
        if participant.active_experiment_variant_id:
            background_tasks.add_task(queue_subagent_eval_for_event, event.id)
    _queue_completed_harness(db, participant, session, background_tasks, "scenario_completion")

    return StepAnswerResponse(
        event=event,
        current_step=session.current_step,
        next_step_id=None if session.current_step == "complete" else session.current_step,
        completed_step_ids=_completed_step_ids(db, session.id),
        is_ready_to_complete=session.current_step == "complete",
    )


@router.post("/{session_id}/complete", response_model=SessionStateResponse)
def complete_session(
    session_id: str,
    payload: SessionCompleteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SessionStateResponse:
    participant = find_by_raw_token(db, payload.token)
    if participant is None or participant.status in {TokenStatus.revoked, TokenStatus.expired}:
        raise HTTPException(status_code=400, detail="Token is invalid or unavailable")

    session = db.get(ParticipantSession, session_id)
    if session is None or session.token_id != participant.id:
        raise HTTPException(status_code=404, detail="Session not found for token")
    if session.current_step != "complete" and session.status != SessionStatus.completed:
        raise HTTPException(status_code=400, detail="Adaptive scenario is not complete yet")

    completed_now = session.status != SessionStatus.completed
    if completed_now:
        _mark_completed(db, participant, session, _session_events(db, session.id))
        db.commit()
        db.refresh(session)
    if completed_now:
        _queue_completed_harness(db, participant, session, background_tasks, "scenario_completion")
    return _session_state(db, session)


def _queue_completed_harness(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    background_tasks: BackgroundTasks,
    trigger_reason: str,
) -> None:
    if session.status != SessionStatus.completed:
        return
    run = queue_harness_run(db, participant, trigger_reason)
    if run is not None:
        background_tasks.add_task(run_harness_job, run.id)
    sync_run = queue_openviking_sync(db, participant, trigger_reason)
    if sync_run is not None:
        background_tasks.add_task(run_openviking_sync_job, sync_run.id)


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

    _advance_session(db, participant, session, _session_events(db, session.id))
    db.commit()
    db.refresh(event)
    db.refresh(session)
    return event


def _answer_generated_step(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    step: dict[str, Any],
    answer: dict[str, Any],
    requested_answer_mode: str | None = None,
) -> RawEvent:
    step_type = str(step.get("type"))
    answer_mode = _answer_mode(step, answer, requested_answer_mode)
    if step_type in {"triad", "duel"}:
        if answer_mode == "indifferent":
            normalized_answer = _indifferent_answer(answer)
        elif answer_mode == "custom_text":
            normalized_answer = _choice_text_answer(answer)
        else:
            normalized_answer = _choice_answer(step, answer)
    elif step_type == "context_flip":
        normalized_answer = _text_answer(step, answer)
    elif step_type == "correction":
        normalized_answer = _text_answer(step, answer)
    elif step_type == "twin_rank":
        normalized_answer = _twin_rank_answer(step, answer)
    else:
        raise HTTPException(status_code=400, detail="Unsupported generated step type")

    event = _create_step_event(db, participant, session, step, normalized_answer, answer_mode)
    participant.status = TokenStatus.in_progress
    session.status = SessionStatus.in_progress
    db.commit()
    db.refresh(event)

    events = _session_events(db, session.id)
    if step_type in {"triad", "duel"} and answer_mode == "binary":
        _apply_generation_result(
            participant,
            record_adaptive_choice_signal(
                participant=participant,
                last_step=step,
                last_answer=normalized_answer,
                adaptive_answer_count=_adaptive_answer_count(events),
            ),
        )

    _advance_session(db, participant, session, events)
    db.commit()
    db.refresh(event)
    db.refresh(session)
    return event


def _advance_session(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    events: list[RawEvent],
) -> None:
    if _flow_ready_to_complete(participant, events):
        _mark_completed(db, participant, session, events)
        return

    next_step = _next_generated_step(participant, events)
    if next_step is None:
        _mark_completed(db, participant, session, events)
        return

    next_step = _decorate_v2_step(participant, next_step, events)
    _append_adaptive_step(participant, next_step)
    session.current_step = next_step["id"]


def _next_generated_step(participant: ParticipantToken, events: list[RawEvent]) -> dict[str, Any] | None:
    pending_context = _pending_context_flip_event(events)
    if pending_context is not None:
        replay_index = _replay_index_from_event(pending_context) or max(1, _context_flip_answer_count(events))
        result = generate_twin_rank_step(
            participant=participant,
            events=events,
            context_event=pending_context,
            replay_index=replay_index,
        )
        _apply_generation_result(participant, result)
        return result.next_step

    correction_step = _next_v2_correction_step(participant, events)
    if correction_step is not None:
        return correction_step

    adaptive_count = _adaptive_answer_count(events)
    if _should_generate_context_flip(participant, events):
        replay_index = _context_flip_answer_count(events) + 1
        result = generate_context_flip_step(
            participant=participant,
            events=events,
            replay_index=replay_index,
            adaptive_answer_count=adaptive_count,
        )
        _apply_generation_result(participant, result)
        return result.next_step

    result = generate_adaptive_step(
        participant=participant,
        events=events,
        last_step=None,
        last_answer=None,
        adaptive_answer_count=adaptive_count,
    )
    _apply_generation_result(participant, result)
    if result.next_step is None and result.metadata.get("status") == "council_failed":
        return None
    if result.should_complete:
        if _twin_rank_answer_count(events) >= REPLAY_SCENARIO_COUNT:
            return None
        if _context_flip_answer_count(events) < REPLAY_SCENARIO_COUNT and adaptive_count >= MIN_REPLAY_START_QUESTIONS:
            replay_index = _context_flip_answer_count(events) + 1
            replay_result = generate_context_flip_step(
                participant=participant,
                events=events,
                replay_index=replay_index,
                adaptive_answer_count=adaptive_count,
            )
            _apply_generation_result(participant, replay_result)
            return replay_result.next_step

    return result.next_step or fallback_step(adaptive_count + 1)


def _flow_ready_to_complete(participant: ParticipantToken, events: list[RawEvent]) -> bool:
    return (
        _twin_rank_answer_count(events) >= REPLAY_SCENARIO_COUNT
        and should_complete(_adaptive_answer_count(events), _state_confidence(participant))
    )


def _should_generate_context_flip(participant: ParticipantToken, events: list[RawEvent]) -> bool:
    adaptive_count = _adaptive_answer_count(events)
    context_count = _context_flip_answer_count(events)
    if context_count >= REPLAY_SCENARIO_COUNT or _pending_context_flip_event(events) is not None:
        return False
    if adaptive_count < MIN_REPLAY_START_QUESTIONS:
        return False
    if adaptive_count >= MAX_ADAPTIVE_QUESTIONS:
        return True
    if should_complete(adaptive_count, _state_confidence(participant)):
        return True
    return _stable_replay_pick(participant, events)


def _next_v2_correction_step(participant: ParticipantToken, events: list[RawEvent]) -> dict[str, Any] | None:
    if not participant.active_experiment_variant_id:
        return None
    adaptive_count = _adaptive_answer_count(events)
    if adaptive_count <= 0 or adaptive_count % 6 != 0:
        return None
    step_id = f"correction_{adaptive_count // 6}"
    if any(isinstance(event.payload, dict) and event.payload.get("step_id") == step_id for event in events):
        return None
    context_items = _preliminary_twin_read(participant, events)
    return {
        "id": step_id,
        "type": "correction",
        "title": "Preliminary Twin Read",
        "prompt": "What is wrong, incomplete, or overconfident in this read of how you make decisions?",
        "context_title": "Preliminary twin read",
        "context_items": context_items,
        "context_kind": "preliminary_twin_read",
    }


def _decorate_v2_step(participant: ParticipantToken, step: dict[str, Any], events: list[RawEvent]) -> dict[str, Any]:
    if not participant.active_experiment_variant_id:
        return step
    decorated = dict(step)
    modifiers = participant.dynamic_flow_modifiers if isinstance(participant.dynamic_flow_modifiers, dict) else {}
    warmup_count = int(modifiers.get("warmup_event_count") or 3)
    holdout_every_n = max(2, int(modifiers.get("holdout_every_n") or 5))
    target_holdout_count = max(0, int(modifiers.get("target_holdout_count") or 10))
    answered_count = _generated_answer_event_count(events)
    holdout_count = _holdout_event_count(events)

    decorated["phase"] = "warmup" if answered_count < warmup_count else "main_probe"
    if (
        decorated.get("type") in {"triad", "duel", "twin_rank"}
        and isinstance(decorated.get("options"), list)
        and answered_count >= warmup_count
        and holdout_count < target_holdout_count
        and (answered_count + 1) % holdout_every_n == 0
    ):
        decorated["holdout_slot"] = True
        decorated["holdout_partition"] = "v2_periodic"
        decorated["phase"] = "holdout"
    else:
        decorated.setdefault("holdout_slot", False)
    return decorated


def _preliminary_twin_read(participant: ParticipantToken, events: list[RawEvent]) -> list[str]:
    state = participant.adaptive_scenario_state if isinstance(participant.adaptive_scenario_state, dict) else {}
    axis_scores = state.get("axis_scores") if isinstance(state.get("axis_scores"), dict) else {}
    top_axes = sorted(axis_scores.items(), key=lambda item: item[1], reverse=True)[:3]
    items = [f"Current confidence: {round(_state_confidence(participant) * 100)}%"]
    for axis, score in top_axes:
        if score:
            items.append(f"Repeated signal: {axis.replace('_', ' ')} ({score})")
    latest_text = _latest_answer_text(events)
    if latest_text:
        items.append(f"Recent answer signal: {latest_text[:220]}")
    if len(items) == 1:
        items.append("Not enough signal yet; use this correction to name what the model should watch for.")
    return items[:4]


def _latest_answer_text(events: list[RawEvent]) -> str | None:
    for event in reversed(events):
        payload = event.payload if isinstance(event.payload, dict) else {}
        answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}
        for key in ("selected_option", "text", "correction_text"):
            value = answer.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _generated_answer_event_count(events: list[RawEvent]) -> int:
    return sum(
        1
        for event in events
        if isinstance(event.payload, dict)
        and event.event_type != "scenario_completed"
        and event.payload.get("step_type") not in {None, "onboarding"}
    )


def _holdout_event_count(events: list[RawEvent]) -> int:
    return sum(1 for event in events if bool(getattr(event, "holdout_slot", False)))


def _stable_replay_pick(participant: ParticipantToken, events: list[RawEvent]) -> bool:
    seed = ":".join(
        [
            participant.id,
            str(_adaptive_answer_count(events)),
            str(_context_flip_answer_count(events)),
            str(_twin_rank_answer_count(events)),
            str(len(events)),
        ]
    )
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
    return value < 40


def _pending_context_flip_event(events: list[RawEvent]) -> RawEvent | None:
    ranked_replay_ids = {
        replay_id
        for event in events
        if (event.payload if isinstance(event.payload, dict) else {}).get("step_type") == "twin_rank"
        for replay_id in [_replay_id_from_event(event)]
        if replay_id
    }
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("step_type") == "context_flip":
            replay_id = _replay_id_from_event(event)
            if replay_id and replay_id not in ranked_replay_ids:
                return event
    return None


def _state_confidence(participant: ParticipantToken) -> float:
    state = participant.adaptive_scenario_state if isinstance(participant.adaptive_scenario_state, dict) else {}
    try:
        return max(0.0, min(1.0, float(state.get("confidence", 0.0))))
    except (TypeError, ValueError):
        return 0.0


def _create_step_event(
    db: Session,
    participant: ParticipantToken,
    session: ParticipantSession,
    step: dict[str, Any],
    answer: dict[str, Any],
    answer_mode: str = "binary",
) -> RawEvent:
    event_step_type = "indifference" if answer_mode == "indifferent" else step["type"]
    event_payload = {
        "step_id": step["id"],
        "step_type": event_step_type,
        "original_step_type": step["type"],
        "answer_mode": answer_mode,
        "answer": answer,
        "step_snapshot": step,
    }
    if step.get("replay_scenario_id"):
        event_payload["replay_scenario_id"] = step["replay_scenario_id"]
    if step.get("phase"):
        event_payload["phase"] = step["phase"]
    if step.get("holdout_slot"):
        event_payload["holdout_slot"] = True
        event_payload["holdout_partition"] = step.get("holdout_partition") or "v2_periodic"

    event = RawEvent(
        token_id=participant.id,
        session_id=session.id,
        event_type=event_type_for_step(event_step_type),
        payload=event_payload,
        holdout_slot=bool(step.get("holdout_slot")),
        holdout_partition=step.get("holdout_partition"),
        answer_mode=answer_mode,
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

    _advance_session(db, participant, session, events)


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
        replay_context_count=_context_flip_answer_count(events),
        replay_scenario_count=_twin_rank_answer_count(events),
        max_replay_scenarios=REPLAY_SCENARIO_COUNT,
        twin_responses_per_replay=TWIN_RESPONSES_PER_REPLAY,
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
                    "replay_context_count": _context_flip_answer_count(events),
                    "replay_scenario_count": _twin_rank_answer_count(events),
                    "confidence": (participant.adaptive_scenario_state or {}).get("confidence"),
                },
            )
        )
    session.status = SessionStatus.completed
    session.current_step = "complete"
    participant.status = TokenStatus.completed
    participant.initialization_status = "ready_to_train"
    participant.completed_at = datetime.now(timezone.utc)
    if participant.active_experiment_variant_id:
        finalize_calibration(db, participant)


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


def _answer_mode(step: dict[str, Any], answer: dict[str, Any], requested: str | None) -> str:
    raw_mode = requested or answer.get("mode") or answer.get("answer_mode")
    if isinstance(raw_mode, str):
        normalized = raw_mode.strip().lower()
        if normalized in {"binary", "indifferent", "custom_text", "chat"}:
            return normalized
    if step.get("type") in {"context_flip", "correction"}:
        return "custom_text"
    if step.get("type") == "twin_rank":
        return "binary"
    if isinstance(answer.get("text"), str) and not isinstance(answer.get("selected_index"), int):
        return "custom_text"
    return "binary"


def _indifferent_answer(answer: dict[str, Any]) -> dict[str, Any]:
    text = answer.get("text")
    normalized: dict[str, Any] = {"mode": "indifferent"}
    if isinstance(text, str) and text.strip():
        normalized["text"] = text.strip()[:2000]
    return normalized


def _choice_text_answer(answer: dict[str, Any]) -> dict[str, Any]:
    value = answer.get("text") or answer.get("custom_text")
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="text is required for a custom answer")
    text = value.strip()
    if len(text) < 1:
        raise HTTPException(status_code=400, detail="text is required for a custom answer")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="text must be 2000 characters or fewer")
    return {"mode": "custom_text", "text": text}


def _text_answer(step: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    value = answer.get("text")
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="text is required")
    text = value.strip()
    if len(text) < 1:
        raise HTTPException(status_code=400, detail="text is required")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="text must be 2000 characters or fewer")
    normalized: dict[str, Any] = {"text": text}
    if step.get("replay_scenario_id"):
        normalized["replay_scenario_id"] = step["replay_scenario_id"]
    return normalized


def _twin_rank_answer(step: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    options = step.get("options") or []
    if len(options) != TWIN_RESPONSES_PER_REPLAY:
        raise HTTPException(status_code=400, detail="twin_rank steps require exactly three options")

    ranked_options = answer.get("ranked_options")
    if not isinstance(ranked_options, list) or len(ranked_options) != len(options):
        raise HTTPException(status_code=400, detail="ranked_options must rank all twin responses")
    if any(not isinstance(option, str) for option in ranked_options):
        raise HTTPException(status_code=400, detail="ranked_options must contain response text")
    if set(ranked_options) != set(options) or len(set(ranked_options)) != len(options):
        raise HTTPException(status_code=400, detail="ranked_options must match each available response exactly once")

    rejected_options = answer.get("rejected_options", [])
    if rejected_options is None:
        rejected_options = []
    if not isinstance(rejected_options, list) or any(not isinstance(option, str) for option in rejected_options):
        raise HTTPException(status_code=400, detail="rejected_options must be a list of response text")
    rejected = [option for option in rejected_options if option in options]

    correction_value = answer.get("correction_text") or answer.get("correction") or ""
    if not isinstance(correction_value, str):
        raise HTTPException(status_code=400, detail="correction_text must be text")
    correction_text = correction_value.strip()
    if len(correction_text) > 2000:
        raise HTTPException(status_code=400, detail="correction_text must be 2000 characters or fewer")

    normalized: dict[str, Any] = {
        "ranked_options": ranked_options,
        "rejected_options": rejected,
        "correction_text": correction_text,
    }
    if step.get("replay_scenario_id"):
        normalized["replay_scenario_id"] = step["replay_scenario_id"]
    return normalized


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
        and (
            event.payload.get("step_type") in {"triad", "duel", "indifference"}
            or event.payload.get("original_step_type") in {"triad", "duel"}
        )
        and str(event.payload.get("step_id", "")).startswith("adaptive_q_")
    )


def _context_flip_answer_count(events: list[RawEvent]) -> int:
    return _step_type_count(events, "context_flip")


def _twin_rank_answer_count(events: list[RawEvent]) -> int:
    return _step_type_count(events, "twin_rank")


def _step_type_count(events: list[RawEvent], step_type: str) -> int:
    return sum(
        1
        for event in events
        if isinstance(event.payload, dict)
        and event.payload.get("step_type") == step_type
    )


def _replay_id_from_event(event: RawEvent) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    direct = payload.get("replay_scenario_id")
    if isinstance(direct, str) and direct:
        return direct
    answer = payload.get("answer")
    if isinstance(answer, dict) and isinstance(answer.get("replay_scenario_id"), str):
        return str(answer["replay_scenario_id"])
    step = payload.get("step_snapshot")
    if isinstance(step, dict) and isinstance(step.get("replay_scenario_id"), str):
        return str(step["replay_scenario_id"])
    step_id = str(payload.get("step_id", ""))
    for prefix in ("context_flip_", "twin_rank_"):
        if step_id.startswith(prefix):
            return f"replay_{step_id.removeprefix(prefix)}"
    return None


def _replay_index_from_event(event: RawEvent) -> int | None:
    replay_id = _replay_id_from_event(event)
    if not replay_id:
        return None
    try:
        return int(replay_id.rsplit("_", 1)[-1])
    except ValueError:
        return None


def _adaptive_steps(participant: ParticipantToken) -> list[dict[str, Any]]:
    value = participant.adaptive_scenario_steps
    return list(value) if isinstance(value, list) else []
