from datetime import datetime

from pydantic import BaseModel, Field

from app.models import AnalysisStatus, ErrorCategory, EvidenceType, SessionStatus, TokenStatus, WorkflowStatus


class TokenCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None


class TokenResponse(BaseModel):
    id: str
    label: str
    status: TokenStatus
    auth_key: str | None = None
    created_at: datetime
    expires_at: datetime | None
    first_used_at: datetime | None
    last_seen_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class TokenCreateResponse(BaseModel):
    token: str
    invite_url: str
    participant: TokenResponse


class TokenValidateRequest(BaseModel):
    token: str = Field(min_length=16)


class TokenValidateResponse(BaseModel):
    valid: bool
    participant_id: str | None = None
    status: TokenStatus | None = None
    session_id: str | None = None
    message: str


class EventCreateRequest(BaseModel):
    token: str = Field(min_length=16)
    session_id: str | None = None
    event_type: str = Field(min_length=1, max_length=120)
    payload: dict = Field(default_factory=dict)


class EventResponse(BaseModel):
    id: str
    token_id: str
    session_id: str | None
    event_type: str
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminActivityResponse(EventResponse):
    token_label: str | None = None


class SessionResponse(BaseModel):
    id: str
    token_id: str
    status: SessionStatus
    current_step: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunResponse(BaseModel):
    id: str
    token_id: str | None
    name: str
    status: WorkflowStatus
    input_summary: str | None
    output_summary: str | None
    error_summary: str | None
    metadata_json: dict
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ErrorReportResponse(BaseModel):
    id: str
    token_id: str | None
    category: ErrorCategory
    severity: str
    summary: str
    raw_detail: str | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScenarioStep(BaseModel):
    id: str
    type: str
    title: str
    prompt: str
    options: list[str] | None = None
    context_title: str | None = None
    context_items: list[str] | None = None


class SessionStartRequest(BaseModel):
    token: str = Field(min_length=16)


class SessionStateResponse(BaseModel):
    session_id: str
    token_id: str
    token_status: TokenStatus
    session_status: SessionStatus
    current_step: str
    steps: list[ScenarioStep]
    completed_step_ids: list[str]
    event_count: int
    adaptive_question_count: int = 0
    max_adaptive_questions: int = 8
    scenario_generation_status: str | None = None
    scenario_generation_message: str | None = None


class StepAnswerRequest(BaseModel):
    token: str = Field(min_length=16)
    step_id: str = Field(min_length=1)
    step_type: str = Field(min_length=1)
    answer: dict = Field(default_factory=dict)


class StepAnswerResponse(BaseModel):
    event: EventResponse
    current_step: str
    next_step_id: str | None
    completed_step_ids: list[str]
    is_ready_to_complete: bool


class SessionCompleteRequest(BaseModel):
    token: str = Field(min_length=16)


class AdminTokenSummaryResponse(TokenResponse):
    current_step: str | None = None
    session_status: SessionStatus | None = None
    event_count: int = 0
    latest_analysis_status: AnalysisStatus | None = None
    evidence_count: int = 0
    invite_url: str | None = None


class AnalysisArtifactResponse(BaseModel):
    id: str
    analysis_run_id: str
    artifact_type: str
    source_event_ids: list[str]
    payload: dict
    validation_status: str
    confidence: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BehavioralEvidenceResponse(BaseModel):
    id: str
    token_id: str
    session_id: str | None
    analysis_run_id: str
    source_event_ids: list[str]
    evidence_type: EvidenceType
    summary: str
    supporting_quote: str | None
    structured_payload: dict
    confidence: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisRunResponse(BaseModel):
    id: str
    token_id: str
    session_id: str | None
    status: AnalysisStatus
    analysis_type: str
    prompt_version: str
    model_name: str
    input_summary: str | None
    output_summary: str | None
    error_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisRunDetailResponse(AnalysisRunResponse):
    artifacts: list[AnalysisArtifactResponse] = []
    evidence: list[BehavioralEvidenceResponse] = []


class AdminTokenDetailResponse(BaseModel):
    participant: AdminTokenSummaryResponse
    sessions: list[SessionResponse]
    events: list[EventResponse]
    analysis_runs: list[AnalysisRunResponse]
    evidence: list[BehavioralEvidenceResponse]
