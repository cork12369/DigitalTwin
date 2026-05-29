from datetime import datetime

from pydantic import BaseModel, Field

from app.models import AnalysisStatus, ErrorCategory, EvidenceType, HarnessStatus, SessionStatus, TokenStatus, WorkflowStatus


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
    initialization_status: str = "not_started"
    calibration_band: str = "unmeasured"
    calibration_ece: float | None = None
    calibration_temperature: float = 1.0
    active_experiment_variant_id: str | None = None

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
    holdout_slot: bool = False
    holdout_partition: str | None = None
    answer_mode: str = "binary"
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


class OpenVikingStatusResponse(BaseModel):
    configured: bool
    status: str
    base_url: str | None = None
    message: str
    detail: dict = Field(default_factory=dict)


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
    replay_scenario_id: str | None = None
    replay_index: int | None = None
    source_context_step_id: str | None = None
    context_kind: str | None = None
    holdout_slot: bool | None = None
    holdout_partition: str | None = None
    phase: str | None = None


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
    replay_context_count: int = 0
    replay_scenario_count: int = 0
    max_replay_scenarios: int = 2
    twin_responses_per_replay: int = 3
    scenario_generation_status: str | None = None
    scenario_generation_message: str | None = None


class StepAnswerRequest(BaseModel):
    token: str = Field(min_length=16)
    step_id: str = Field(min_length=1)
    step_type: str = Field(min_length=1)
    answer: dict = Field(default_factory=dict)
    answer_mode: str | None = Field(default=None, max_length=20)


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


class TwinHarnessScoreResponse(BaseModel):
    id: str
    harness_run_id: str
    case_id: str
    token_id: str
    source_type: str
    source_id: str | None
    source_label: str | None
    metric_type: str
    base_logprob: float
    conditioned_logprob: float
    lift: float
    information_gain_bits: float
    kl_divergence: float
    verdict: str
    distribution_base: dict
    distribution_conditioned: dict
    metadata_json: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class TwinHarnessCaseResponse(BaseModel):
    id: str
    harness_run_id: str
    token_id: str
    target_event_id: str | None
    target_step_id: str | None
    target_step_type: str
    replay_scenario_id: str | None
    human_target_label: str
    human_target_text: str
    candidate_actions: list[dict]
    baseline_prompt: str
    metadata_json: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class TwinHarnessRunResponse(BaseModel):
    id: str
    token_id: str
    status: HarnessStatus
    trigger_reason: str
    model_name: str
    prompt_version: str
    input_summary: str | None
    output_summary: str | None
    error_summary: str | None
    aggregate_metrics: dict
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TwinHarnessRunDetailResponse(TwinHarnessRunResponse):
    cases: list[TwinHarnessCaseResponse] = []
    scores: list[TwinHarnessScoreResponse] = []


class OpenVikingTokenStateResponse(BaseModel):
    token_id: str
    root_uri: str
    status: OpenVikingStatusResponse
    latest_sync_run: WorkflowRunResponse | None = None
    latest_test_run: TwinHarnessRunResponse | None = None
    mirrored_source_count: int = 0
    last_error: str | None = None


class AdminTokenDetailResponse(BaseModel):
    participant: AdminTokenSummaryResponse
    sessions: list[SessionResponse]
    events: list[EventResponse]
    analysis_runs: list[AnalysisRunResponse]
    evidence: list[BehavioralEvidenceResponse]
    latest_harness_run: TwinHarnessRunResponse | None = None


class TrainingStartRequest(BaseModel):
    token: str = Field(min_length=16)


class TrainingChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    message_index: int
    pair_index: int | None
    metadata_json: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class TrainingStateResponse(BaseModel):
    token_id: str
    chat_session_id: str
    initialization_status: str
    guide_custom_prompt: str | None = None
    messages: list[TrainingChatMessageResponse]
    readiness: dict
    pair_count: int
    pair_block_size: int
    draft_card_count: int
    latest_compaction_run_id: str | None = None
    latest_compaction_status: str | None = None
    compaction_notice: str | None = None


class TrainingMessageCreateRequest(BaseModel):
    token: str = Field(min_length=16)
    content: str = Field(min_length=1, max_length=5000)


class GuideSettingsUpdateRequest(BaseModel):
    token: str = Field(min_length=16)
    custom_prompt: str | None = Field(default=None, max_length=1200)


class MemoryCardsListRequest(BaseModel):
    token: str = Field(min_length=16)


class MemoryCardPillarLinkResponse(BaseModel):
    id: str | None = None
    pillar_key: str
    weight: float
    cumulative_delta_w: float = 0.0
    update_count: int = 0
    last_updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class MemoryCardDuplicateSuggestionResponse(BaseModel):
    id: str
    candidate_card_id: str
    matched_card_id: str
    matched_card_title: str | None = None
    status: str
    confidence: str
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryCardResponse(BaseModel):
    id: str
    title: str
    body: str
    status: str
    priority: str
    card_type: str = "disposition"
    seed_source: str = "compaction"
    reinforcement_count: int = 0
    promoted_at: datetime | None = None
    source_quote: str | None
    pillar_links: list[MemoryCardPillarLinkResponse]
    duplicate_suggestions: list[MemoryCardDuplicateSuggestionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryCardsResponse(BaseModel):
    token_id: str
    pillars: list[dict]
    priority_weights: dict
    readiness: dict
    cards: list[MemoryCardResponse]


class MemoryCardUpdateRequest(BaseModel):
    token: str = Field(min_length=16)
    title: str | None = Field(default=None, max_length=180)
    body: str | None = Field(default=None, max_length=1200)
    status: str | None = Field(default=None, max_length=40)
    priority: str | None = Field(default=None, max_length=40)
    pillar_keys: list[str] | None = None


class MemoryCardDeleteRequest(BaseModel):
    token: str = Field(min_length=16)


class TrainingDiagnosticsResponse(BaseModel):
    token_id: str
    readiness: dict
    graph: dict
    latest_snapshot: dict | None = None


class V2PreseedCardsResponse(BaseModel):
    token_id: str
    created_or_existing_count: int
    cards: list[MemoryCardResponse]


class ExperimentVariantResponse(BaseModel):
    id: str
    label: str
    delta_w_matrix: dict
    subagent_model_id: str
    subagent_reasoning_effort: str
    prompt_template_hash: str
    session_time_budget_seconds: int
    target_accuracy_band: dict
    created_at: datetime


class SubagentVerdictResponse(BaseModel):
    id: str
    raw_event_id: str
    card_id: str
    polarity: str
    confidence: float
    spectrum_position: float | None
    delta_w_applied: float
    rationale: str
    model_latency_ms: int
    created_at: datetime


class V2StateResponse(BaseModel):
    token_id: str
    v2_enabled: bool
    calibration_band: str
    calibration_ece: float | None
    calibration_temperature: float
    active_variant: ExperimentVariantResponse | None = None
    event_counts: dict
    cards: list[dict]
    recent_verdicts: list[SubagentVerdictResponse]
