import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, Integer, JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class TokenStatus(str, enum.Enum):
    generated = "generated"
    active = "active"
    in_progress = "in_progress"
    completed = "completed"
    errored = "errored"
    revoked = "revoked"
    expired = "expired"
    reset = "reset"


class SessionStatus(str, enum.Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    completed = "completed"
    errored = "errored"


class WorkflowStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    retrying = "retrying"


class ErrorCategory(str, enum.Enum):
    workflow = "workflow"
    model_provider = "model_provider"
    validation = "validation"
    graph_update = "graph_update"
    memory_retrieval = "memory_retrieval"
    infrastructure = "infrastructure"


class AnalysisStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    needs_review = "needs_review"


class HarnessStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    unsupported_model = "unsupported_model"


class EvidenceType(str, enum.Enum):
    noticed_first = "noticed_first"
    value_signal = "value_signal"
    tradeoff_preference = "tradeoff_preference"
    context_flip = "context_flip"
    correction = "correction"
    conditional_policy = "conditional_policy"
    ambiguity_frame = "ambiguity_frame"
    twin_ranking = "twin_ranking"


class ParticipantToken(Base):
    __tablename__ = "participant_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    auth_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TokenStatus] = mapped_column(Enum(TokenStatus), default=TokenStatus.active, index=True)
    user_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    profile_source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_structured_context: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    profile_llm_summary: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    profile_ingestion_metadata: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    adaptive_scenario_steps: Mapped[list[dict] | None] = mapped_column(JSON, default=list, nullable=True)
    adaptive_scenario_state: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    scenario_generation_metadata: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    initialization_status: Mapped[str] = mapped_column(String(40), default="not_started", nullable=False)
    guide_persona: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    guide_custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_readiness_snapshot: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions: Mapped[list["ParticipantSession"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    events: Mapped[list["RawEvent"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    errors: Mapped[list["ErrorReport"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    training_chat_sessions: Mapped[list["TrainingChatSession"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    training_messages: Mapped[list["TrainingChatMessage"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    memory_cards: Mapped[list["MemoryCard"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    compaction_runs: Mapped[list["MemoryCompactionRun"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    coverage_snapshots: Mapped[list["CoverageGraphSnapshot"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    duplicate_suggestions: Mapped[list["MemoryCardDuplicateSuggestion"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    harness_runs: Mapped[list["TwinHarnessRun"]] = relationship(back_populates="token", cascade="all, delete-orphan")


class ParticipantSession(Base):
    __tablename__ = "participant_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), default=SessionStatus.not_started, index=True)
    current_step: Mapped[str] = mapped_column(String(120), default="onboarding_profile")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    token: Mapped[ParticipantToken] = relationship(back_populates="sessions")
    events: Mapped[list["RawEvent"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class RawEvent(Base):
    __tablename__ = "raw_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("participant_sessions.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    token: Mapped[ParticipantToken] = relationship(back_populates="events")
    session: Mapped[ParticipantSession | None] = relationship(back_populates="events")


class TrainingChatSession(Base):
    __tablename__ = "training_chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    pair_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compacted_pair_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    token: Mapped[ParticipantToken] = relationship(back_populates="training_chat_sessions")
    messages: Mapped[list["TrainingChatMessage"]] = relationship(back_populates="chat_session", cascade="all, delete-orphan")


class TrainingChatMessage(Base):
    __tablename__ = "training_chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    chat_session_id: Mapped[str] = mapped_column(ForeignKey("training_chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(40), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_index: Mapped[int] = mapped_column(Integer, nullable=False)
    pair_index: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    token: Mapped[ParticipantToken] = relationship(back_populates="training_messages")
    chat_session: Mapped[TrainingChatSession] = relationship(back_populates="messages")


class MemoryCompactionRun(Base):
    __tablename__ = "memory_compaction_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    chat_session_id: Mapped[str] = mapped_column(ForeignKey("training_chat_sessions.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    start_pair_index: Mapped[int] = mapped_column(Integer, nullable=False)
    end_pair_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    token: Mapped[ParticipantToken] = relationship(back_populates="compaction_runs")


class MemoryCard(Base):
    __tablename__ = "memory_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    source_chat_session_id: Mapped[str | None] = mapped_column(ForeignKey("training_chat_sessions.id"), nullable=True, index=True)
    source_compaction_run_id: Mapped[str | None] = mapped_column(ForeignKey("memory_compaction_runs.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    priority: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    token: Mapped[ParticipantToken] = relationship(back_populates="memory_cards")
    pillar_links: Mapped[list["MemoryCardPillarLink"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    candidate_duplicate_suggestions: Mapped[list["MemoryCardDuplicateSuggestion"]] = relationship(
        back_populates="candidate_card",
        foreign_keys="MemoryCardDuplicateSuggestion.candidate_card_id",
        cascade="all, delete-orphan",
    )
    matched_duplicate_suggestions: Mapped[list["MemoryCardDuplicateSuggestion"]] = relationship(
        back_populates="matched_card",
        foreign_keys="MemoryCardDuplicateSuggestion.matched_card_id",
        cascade="all, delete-orphan",
    )


class MemoryCardPillarLink(Base):
    __tablename__ = "memory_card_pillar_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    card_id: Mapped[str] = mapped_column(ForeignKey("memory_cards.id"), index=True)
    pillar_key: Mapped[str] = mapped_column(String(80), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    card: Mapped[MemoryCard] = relationship(back_populates="pillar_links")


class MemoryCardDuplicateSuggestion(Base):
    __tablename__ = "memory_card_duplicate_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    candidate_card_id: Mapped[str] = mapped_column(ForeignKey("memory_cards.id"), index=True)
    matched_card_id: Mapped[str] = mapped_column(ForeignKey("memory_cards.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    confidence: Mapped[str] = mapped_column(String(20), default="0.0")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    token: Mapped[ParticipantToken] = relationship(back_populates="duplicate_suggestions")
    candidate_card: Mapped[MemoryCard] = relationship(back_populates="candidate_duplicate_suggestions", foreign_keys=[candidate_card_id])
    matched_card: Mapped[MemoryCard] = relationship(back_populates="matched_duplicate_suggestions", foreign_keys=[matched_card_id])


class TwinHarnessRun(Base):
    __tablename__ = "twin_harness_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    status: Mapped[HarnessStatus] = mapped_column(Enum(HarnessStatus), default=HarnessStatus.queued, index=True)
    trigger_reason: Mapped[str] = mapped_column(String(160), default="manual", index=True)
    model_name: Mapped[str] = mapped_column(String(160), default="")
    prompt_version: Mapped[str] = mapped_column(String(120), default="harness_discrete_logprob_v1")
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    aggregate_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    token: Mapped[ParticipantToken] = relationship(back_populates="harness_runs")
    cases: Mapped[list["TwinHarnessCase"]] = relationship(back_populates="harness_run", cascade="all, delete-orphan")
    scores: Mapped[list["TwinHarnessScore"]] = relationship(back_populates="harness_run", cascade="all, delete-orphan")


class TwinHarnessCase(Base):
    __tablename__ = "twin_harness_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    harness_run_id: Mapped[str] = mapped_column(ForeignKey("twin_harness_runs.id"), index=True)
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    target_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    target_step_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    target_step_type: Mapped[str] = mapped_column(String(40), index=True)
    replay_scenario_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    human_target_label: Mapped[str] = mapped_column(String(20))
    human_target_text: Mapped[str] = mapped_column(Text)
    candidate_actions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    baseline_prompt: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    harness_run: Mapped[TwinHarnessRun] = relationship(back_populates="cases")
    scores: Mapped[list["TwinHarnessScore"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class TwinHarnessScore(Base):
    __tablename__ = "twin_harness_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    harness_run_id: Mapped[str] = mapped_column(ForeignKey("twin_harness_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("twin_harness_cases.id"), index=True)
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_label: Mapped[str | None] = mapped_column(String(220), nullable=True)
    metric_type: Mapped[str] = mapped_column(String(60), index=True)
    base_logprob: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conditioned_logprob: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    lift: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    information_gain_bits: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    kl_divergence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    verdict: Mapped[str] = mapped_column(String(60), index=True)
    distribution_base: Mapped[dict] = mapped_column(JSON, default=dict)
    distribution_conditioned: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    harness_run: Mapped[TwinHarnessRun] = relationship(back_populates="scores")
    case: Mapped[TwinHarnessCase] = relationship(back_populates="scores")


class CoverageGraphSnapshot(Base):
    __tablename__ = "coverage_graph_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(80), default="readiness", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    token: Mapped[ParticipantToken] = relationship(back_populates="coverage_snapshots")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str | None] = mapped_column(ForeignKey("participant_tokens.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(Enum(WorkflowStatus), default=WorkflowStatus.queued, index=True)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    token: Mapped[ParticipantToken | None] = relationship(back_populates="workflow_runs")


class ErrorReport(Base):
    __tablename__ = "error_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str | None] = mapped_column(ForeignKey("participant_tokens.id"), nullable=True, index=True)
    category: Mapped[ErrorCategory] = mapped_column(Enum(ErrorCategory), default=ErrorCategory.infrastructure, index=True)
    severity: Mapped[str] = mapped_column(String(40), default="error")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    raw_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    token: Mapped[ParticipantToken | None] = relationship(back_populates="errors")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("participant_sessions.id"), nullable=True, index=True)
    status: Mapped[AnalysisStatus] = mapped_column(Enum(AnalysisStatus), default=AnalysisStatus.queued, index=True)
    analysis_type: Mapped[str] = mapped_column(String(120), default="reliability_first_behavioral_analysis")
    prompt_version: Mapped[str] = mapped_column(String(120), default="reliability_first_v1")
    model_name: Mapped[str] = mapped_column(String(160), default="mock-reliability-extractor")
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    artifacts: Mapped[list["AnalysisArtifact"]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan")
    evidence: Mapped[list["BehavioralEvidence"]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan")


class AnalysisArtifact(Base):
    __tablename__ = "analysis_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(120), index=True)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_status: Mapped[str] = mapped_column(String(80), default="valid")
    confidence: Mapped[str] = mapped_column(String(20), default="0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="artifacts")


class BehavioralEvidence(Base):
    __tablename__ = "behavioral_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(ForeignKey("participant_tokens.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("participant_sessions.id"), nullable=True, index=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType), index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[str] = mapped_column(String(20), default="0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="evidence")
