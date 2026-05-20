from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AnalysisArtifact, AnalysisRun, AnalysisStatus, BehavioralEvidence, ErrorCategory, ErrorReport, EvidenceType, ParticipantToken, RawEvent
from app.scenario import STEP_BY_ID


PROMPT_VERSION = "reliability_first_v1"
MODEL_NAME = "mock-reliability-extractor"


VALUE_MAP = {
    "Risk to people": (EvidenceType.noticed_first, "human impact and safety are noticed early"),
    "Speed of execution": (EvidenceType.value_signal, "speed and momentum are salient values"),
    "Long-term consequences": (EvidenceType.value_signal, "long-term consequence awareness is salient"),
    "Clarify the rules": (EvidenceType.ambiguity_frame, "ambiguity is framed through rules and constraints"),
    "Look for hidden trade-offs": (EvidenceType.ambiguity_frame, "ambiguity is framed through trade-off discovery"),
    "Test with a small action": (EvidenceType.ambiguity_frame, "ambiguity is resolved through reversible experiments"),
    "Transparent reasoning": (EvidenceType.value_signal, "transparent reasoning increases trust"),
    "Past performance": (EvidenceType.value_signal, "track record increases trust"),
    "Alignment with values": (EvidenceType.value_signal, "values alignment increases trust"),
}


TRADEOFF_MAP = {
    "Protect quality even if delivery slows": "quality is preferred over speed when resources are limited",
    "Ship sooner and improve later": "speed is preferred when iteration is possible",
    "More manual control with fewer surprises": "control and predictability are preferred over automation",
    "More automation with more monitoring": "automation is acceptable when monitoring exists",
    "Ask for correction immediately": "correction loops are prioritized over explanation-first behavior",
    "Show why it inferred that answer first": "explainability is prioritized before correction",
}


def _event_step(event: RawEvent) -> dict[str, Any]:
    return STEP_BY_ID.get(event.payload.get("step_id"), {})


def _supporting_quote(event: RawEvent) -> str | None:
    answer = event.payload.get("answer", {})
    return answer.get("text") or answer.get("selected_option") or ", ".join(answer.get("ranked_options", [])) or None


def _confidence(value: float) -> str:
    return f"{value:.2f}"


def _create_artifact(db: Session, run: AnalysisRun, artifact_type: str, source_event_ids: list[str], payload: dict, confidence: float) -> AnalysisArtifact:
    artifact = AnalysisArtifact(
        analysis_run_id=run.id,
        artifact_type=artifact_type,
        source_event_ids=source_event_ids,
        payload=payload,
        validation_status="valid",
        confidence=_confidence(confidence),
    )
    db.add(artifact)
    return artifact


def _create_evidence(
    db: Session,
    run: AnalysisRun,
    event: RawEvent,
    evidence_type: EvidenceType,
    summary: str,
    payload: dict,
    confidence: float,
) -> BehavioralEvidence:
    evidence = BehavioralEvidence(
        token_id=run.token_id,
        session_id=run.session_id,
        analysis_run_id=run.id,
        source_event_ids=[event.id],
        evidence_type=evidence_type,
        summary=summary,
        supporting_quote=_supporting_quote(event),
        structured_payload=payload,
        confidence=_confidence(confidence),
    )
    db.add(evidence)
    return evidence


def _extract_event(db: Session, run: AnalysisRun, event: RawEvent) -> None:
    step = _event_step(event)
    step_type = event.payload.get("step_type")
    answer = event.payload.get("answer", {})
    normalized = {
        "event_id": event.id,
        "step_id": event.payload.get("step_id"),
        "step_type": step_type,
        "prompt": step.get("prompt"),
        "answer": answer,
        "available_options": step.get("options", []),
        "timestamp": event.created_at.isoformat() if event.created_at else None,
    }
    _create_artifact(db, run, "event_normalization", [event.id], normalized, 1.0)

    if step_type == "triad":
        selected = answer.get("selected_option")
        evidence_type, phrase = VALUE_MAP.get(selected, (EvidenceType.value_signal, "selected option indicates a value signal"))
        _create_evidence(
            db,
            run,
            event,
            evidence_type,
            f"Triad selection suggests {phrase}.",
            {"selected_option": selected, "unselected_options": [option for option in step.get("options", []) if option != selected]},
            0.78,
        )
    elif step_type == "duel":
        selected = answer.get("selected_option")
        _create_evidence(
            db,
            run,
            event,
            EvidenceType.tradeoff_preference,
            TRADEOFF_MAP.get(selected, "Duel selection indicates a trade-off preference."),
            {"selected_option": selected, "sacrificed_options": [option for option in step.get("options", []) if option != selected]},
            0.82,
        )
    elif step_type == "context_flip":
        text = answer.get("text", "")
        lower = text.lower()
        flip_detected = any(term in lower for term in ["change", "different", "would", "public", "team", "depends"])
        payload = {
            "flip_detected": flip_detected,
            "possible_triggers": [term for term in ["public", "team", "only me", "accountability", "risk"] if term in lower],
            "analysis_mode": "mock_reliability_first_open_ended",
            "requires_llm_review": True,
        }
        _create_artifact(db, run, "context_flip_analysis", [event.id], payload, 0.70)
        _create_evidence(
            db,
            run,
            event,
            EvidenceType.context_flip,
            "Open-ended context flip answer may indicate a conditional decision policy; flagged for LLM-backed review.",
            payload,
            0.70,
        )
    elif step_type == "correction":
        payload = {
            "correction_text": answer.get("text", ""),
            "analysis_mode": "mock_reliability_first_open_ended",
            "treat_as_high_weight_signal": True,
            "requires_llm_review": True,
        }
        _create_artifact(db, run, "correction_analysis", [event.id], payload, 0.76)
        _create_evidence(
            db,
            run,
            event,
            EvidenceType.correction,
            "User correction captured as a high-weight signal for future twin interpretation repair.",
            payload,
            0.76,
        )
    elif step_type == "twin_rank":
        ranked = answer.get("ranked_options", [])
        _create_evidence(
            db,
            run,
            event,
            EvidenceType.twin_ranking,
            "Twin ranking captures which preliminary interpretation feels closest to the user.",
            {"ranked_options": ranked, "closest": ranked[0] if ranked else None},
            0.74,
        )


def analyze_token(db: Session, participant: ParticipantToken) -> AnalysisRun:
    settings = get_settings()
    session = participant.sessions[-1] if participant.sessions else None
    events = db.query(RawEvent).filter(RawEvent.token_id == participant.id).order_by(RawEvent.created_at.asc()).all()
    run = AnalysisRun(
        token_id=participant.id,
        session_id=session.id if session else None,
        status=AnalysisStatus.running,
        prompt_version=PROMPT_VERSION,
        model_name=settings.openrouter_model if settings.has_openrouter_key else MODEL_NAME,
        input_summary=f"Analyzing {len(events)} raw events with reliability-first multi-pass mock extractor.",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        for event in events:
            _extract_event(db, run, event)

        evidence_count = db.query(BehavioralEvidence).filter(BehavioralEvidence.analysis_run_id == run.id).count()
        _create_artifact(
            db,
            run,
            "consistency_analysis",
            [event.id for event in events],
            {
                "analysis_mode": "mock_reliability_first_consistency_pass",
                "note": "Real LangChain pass should compare all extracted claims for contradictions and conditional policies.",
                "evidence_count": evidence_count,
            },
            0.65,
        )
        _create_artifact(
            db,
            run,
            "value_graph_update_proposal",
            [event.id for event in events],
            {
                "analysis_mode": "mock_value_graph_proposal",
                "status": "proposal_only",
                "note": "Use accepted behavioral evidence to propose value nodes, opposing edges, reinforcing edges, and conditional policy edges in the next graph phase.",
                "evidence_count": evidence_count,
                "requires_llm_review": any(
                    event.payload.get("step_type") in {"context_flip", "correction"}
                    for event in events
                ),
            },
            0.62,
        )
        run.status = AnalysisStatus.completed
        run.output_summary = f"Created {evidence_count} behavioral evidence records. Open-ended answers flagged for LLM review."
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:  # pragma: no cover - defensive failure logging
        run.status = AnalysisStatus.failed
        run.error_summary = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        db.add(
            ErrorReport(
                token_id=participant.id,
                category=ErrorCategory.workflow,
                severity="error",
                summary="Behavioral analysis failed.",
                raw_detail=str(exc),
            )
        )
        db.commit()
        raise