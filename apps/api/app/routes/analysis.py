from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import AnalysisRun, BehavioralEvidence, ParticipantToken
from app.schemas import AnalysisRunDetailResponse, AnalysisRunResponse, BehavioralEvidenceResponse
from app.services.analysis_service import analyze_token

router = APIRouter(prefix="/api/admin", tags=["analysis"])


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