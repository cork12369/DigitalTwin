from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import AnalysisRun, BehavioralEvidence, ErrorReport, ParticipantSession, ParticipantToken, RawEvent, now_utc
from app.schemas import (
    AdminActivityResponse,
    AdminTokenDetailResponse,
    AdminTokenSummaryResponse,
    AnalysisRunDetailResponse,
    AnalysisRunResponse,
    BehavioralEvidenceResponse,
    ErrorReportResponse,
    EventResponse,
    SessionResponse,
)
from app.services.analysis_service import analyze_token

router = APIRouter(prefix="/api/admin", tags=["analysis"])


def _token_summary(db: Session, participant: ParticipantToken) -> AdminTokenSummaryResponse:
    session = (
        db.query(ParticipantSession)
        .filter(ParticipantSession.token_id == participant.id)
        .order_by(ParticipantSession.created_at.desc())
        .first()
    )
    latest_analysis = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.token_id == participant.id)
        .order_by(AnalysisRun.created_at.desc())
        .first()
    )
    event_count = db.query(RawEvent).filter(RawEvent.token_id == participant.id).count()
    evidence_count = db.query(BehavioralEvidence).filter(BehavioralEvidence.token_id == participant.id).count()
    return AdminTokenSummaryResponse.model_validate(participant).model_copy(
        update={
            "current_step": session.current_step if session else None,
            "session_status": session.status if session else None,
            "event_count": event_count,
            "latest_analysis_status": latest_analysis.status if latest_analysis else None,
            "evidence_count": evidence_count,
        }
    )


@router.get("/activity", response_model=list[AdminActivityResponse])
def list_recent_activity(limit: int = 25, token_id: str | None = None, db: Session = Depends(get_db)) -> list[AdminActivityResponse]:
    query = db.query(RawEvent).order_by(RawEvent.created_at.desc())
    if token_id:
        query = query.filter(RawEvent.token_id == token_id)
    events = query.limit(max(1, min(limit, 100))).all()
    token_labels = {
        token.id: token.label
        for token in db.query(ParticipantToken).filter(ParticipantToken.id.in_({event.token_id for event in events})).all()
    } if events else {}
    return [
        AdminActivityResponse.model_validate(event).model_copy(update={"token_label": token_labels.get(event.token_id)})
        for event in events
    ]


@router.get("/analysis-runs", response_model=list[AnalysisRunResponse])
def list_recent_analysis_runs(limit: int = 25, db: Session = Depends(get_db)) -> list[AnalysisRun]:
    return db.query(AnalysisRun).order_by(AnalysisRun.created_at.desc()).limit(max(1, min(limit, 100))).all()


@router.get("/errors", response_model=list[ErrorReportResponse])
def list_error_reports(include_resolved: bool = False, limit: int = 50, db: Session = Depends(get_db)) -> list[ErrorReport]:
    query = db.query(ErrorReport).order_by(ErrorReport.created_at.desc())
    if not include_resolved:
        query = query.filter(ErrorReport.resolved_at.is_(None))
    return query.limit(max(1, min(limit, 100))).all()


@router.post("/errors/{error_id}/resolve", response_model=ErrorReportResponse)
def resolve_error_report(error_id: str, db: Session = Depends(get_db)) -> ErrorReport:
    error = db.get(ErrorReport, error_id)
    if error is None:
        raise HTTPException(status_code=404, detail="Error report not found")
    error.resolved_at = now_utc()
    db.commit()
    db.refresh(error)
    return error


@router.get("/tokens/{token_id}/detail", response_model=AdminTokenDetailResponse)
def get_token_detail(token_id: str, db: Session = Depends(get_db)) -> AdminTokenDetailResponse:
    participant = db.get(ParticipantToken, token_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Token not found")

    sessions = db.query(ParticipantSession).filter(ParticipantSession.token_id == token_id).order_by(ParticipantSession.created_at.desc()).all()
    events = db.query(RawEvent).filter(RawEvent.token_id == token_id).order_by(RawEvent.created_at.desc()).all()
    analysis_runs = db.query(AnalysisRun).filter(AnalysisRun.token_id == token_id).order_by(AnalysisRun.created_at.desc()).all()
    evidence = db.query(BehavioralEvidence).filter(BehavioralEvidence.token_id == token_id).order_by(BehavioralEvidence.created_at.desc()).all()

    return AdminTokenDetailResponse(
        participant=_token_summary(db, participant),
        sessions=[SessionResponse.model_validate(session) for session in sessions],
        events=[EventResponse.model_validate(event) for event in events],
        analysis_runs=[AnalysisRunResponse.model_validate(run) for run in analysis_runs],
        evidence=[BehavioralEvidenceResponse.model_validate(item) for item in evidence],
    )


@router.post("/tokens/{token_id}/analyze", response_model=AnalysisRunResponse)
def analyze_participant_token(token_id: str, db: Session = Depends(get_db)) -> AnalysisRun:
    participant = db.get(ParticipantToken, token_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return analyze_token(db, participant)


@router.get("/tokens/{token_id}/analysis-runs", response_model=list[AnalysisRunResponse])
def list_analysis_runs(token_id: str, db: Session = Depends(get_db)) -> list[AnalysisRun]:
    return db.query(AnalysisRun).filter(AnalysisRun.token_id == token_id).order_by(AnalysisRun.created_at.desc()).all()


@router.get("/analysis-runs/{analysis_run_id}", response_model=AnalysisRunDetailResponse)
def get_analysis_run(analysis_run_id: str, db: Session = Depends(get_db)) -> AnalysisRun:
    run = (
        db.query(AnalysisRun)
        .options(selectinload(AnalysisRun.artifacts), selectinload(AnalysisRun.evidence))
        .filter(AnalysisRun.id == analysis_run_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return run


@router.get("/tokens/{token_id}/evidence", response_model=list[BehavioralEvidenceResponse])
def list_behavioral_evidence(token_id: str, db: Session = Depends(get_db)) -> list[BehavioralEvidence]:
    return db.query(BehavioralEvidence).filter(BehavioralEvidence.token_id == token_id).order_by(BehavioralEvidence.created_at.desc()).all()