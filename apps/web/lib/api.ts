export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export type HealthResponse = {
    status: string;
    [key: string]: unknown;
};

export type ParticipantToken = {
    id: string;
    label: string;
    status: string;
    auth_key?: string | null;
    invite_url?: string | null;
    created_at: string;
    expires_at: string | null;
    first_used_at: string | null;
    last_seen_at: string | null;
    completed_at: string | null;
    initialization_status?: string;
    current_step?: string | null;
    session_status?: string | null;
    event_count?: number;
    latest_analysis_status?: string | null;
    evidence_count?: number;
};

export type RawEvent = {
    id: string;
    token_id: string;
    session_id: string | null;
    event_type: string;
    payload: Record<string, unknown>;
    created_at: string;
    token_label?: string | null;
};

export type AnalysisRun = {
    id: string;
    token_id: string;
    session_id: string | null;
    status: string;
    analysis_type: string;
    prompt_version: string;
    model_name: string;
    input_summary: string | null;
    output_summary: string | null;
    error_summary: string | null;
    started_at: string | null;
    completed_at: string | null;
    created_at: string;
};

export type WorkflowRun = {
    id: string;
    token_id: string | null;
    name: string;
    status: string;
    input_summary: string | null;
    output_summary: string | null;
    error_summary: string | null;
    metadata_json: Record<string, unknown>;
    started_at: string | null;
    completed_at: string | null;
    created_at: string;
};

export type TwinHarnessRun = {
    id: string;
    token_id: string;
    status: string;
    trigger_reason: string;
    model_name: string;
    prompt_version: string;
    input_summary: string | null;
    output_summary: string | null;
    error_summary: string | null;
    aggregate_metrics: Record<string, unknown>;
    started_at: string | null;
    completed_at: string | null;
    created_at: string;
};

export type TwinHarnessCase = {
    id: string;
    harness_run_id: string;
    token_id: string;
    target_event_id: string | null;
    target_step_id: string | null;
    target_step_type: string;
    replay_scenario_id: string | null;
    human_target_label: string;
    human_target_text: string;
    candidate_actions: Array<Record<string, string>>;
    baseline_prompt: string;
    metadata_json: Record<string, unknown>;
    created_at: string;
};

export type TwinHarnessScore = {
    id: string;
    harness_run_id: string;
    case_id: string;
    token_id: string;
    source_type: string;
    source_id: string | null;
    source_label: string | null;
    metric_type: string;
    base_logprob: number;
    conditioned_logprob: number;
    lift: number;
    information_gain_bits: number;
    kl_divergence: number;
    verdict: string;
    distribution_base: Record<string, number>;
    distribution_conditioned: Record<string, number>;
    metadata_json: Record<string, unknown>;
    created_at: string;
};

export type TwinHarnessRunDetail = TwinHarnessRun & {
    cases: TwinHarnessCase[];
    scores: TwinHarnessScore[];
};

export type OpenVikingStatus = {
    configured: boolean;
    status: string;
    base_url: string | null;
    message: string;
    detail: Record<string, unknown>;
};

export type OpenVikingTokenState = {
    token_id: string;
    root_uri: string;
    status: OpenVikingStatus;
    latest_sync_run?: WorkflowRun | null;
    latest_test_run?: TwinHarnessRun | null;
    mirrored_source_count: number;
    last_error?: string | null;
};

export type AnalysisArtifact = {
    id: string;
    analysis_run_id: string;
    artifact_type: string;
    source_event_ids: string[];
    payload: Record<string, unknown>;
    validation_status: string;
    confidence: string;
    created_at: string;
};

export type BehavioralEvidence = {
    id: string;
    token_id: string;
    session_id: string | null;
    analysis_run_id: string;
    source_event_ids: string[];
    evidence_type: string;
    summary: string;
    supporting_quote: string | null;
    structured_payload: Record<string, unknown>;
    confidence: string;
    created_at: string;
};

export type ErrorReport = {
    id: string;
    token_id: string | null;
    category: string;
    severity: string;
    summary: string;
    raw_detail: string | null;
    resolved_at: string | null;
    created_at: string;
};

export type SessionSummary = {
    id: string;
    token_id: string;
    status: string;
    current_step: string;
    created_at: string;
    updated_at: string;
};

export type TrainingMessage = {
    id: string;
    role: string;
    content: string;
    message_index: number;
    pair_index: number | null;
    metadata_json: Record<string, unknown>;
    created_at: string;
};

export type ReadinessPillar = {
    key: string;
    label: string;
    description: string;
    score: number;
    target: number;
    percent: number;
    reviewed_card_count: number;
};

export type ReadinessState = {
    status: string;
    ready_for_twin: boolean;
    overall_percent: number;
    total_points: number;
    target_points: number;
    priority_weights: Record<string, number>;
    pillars: ReadinessPillar[];
    reviewed_card_count: number;
    draft_card_count: number;
    updated_at: string;
};

export type TrainingState = {
    token_id: string;
    chat_session_id: string;
    initialization_status: string;
    guide_custom_prompt?: string | null;
    messages: TrainingMessage[];
    readiness: ReadinessState;
    pair_count: number;
    pair_block_size: number;
    draft_card_count: number;
    latest_compaction_run_id?: string | null;
    latest_compaction_status?: string | null;
    compaction_notice?: string | null;
};

export type MemoryCardPillarLink = {
    pillar_key: string;
    weight: number;
};

export type MemoryCardDuplicateSuggestion = {
    id: string;
    candidate_card_id: string;
    matched_card_id: string;
    matched_card_title?: string | null;
    status: string;
    confidence: string;
    reason?: string | null;
    created_at: string;
};

export type MemoryCard = {
    id: string;
    title: string;
    body: string;
    status: string;
    priority: string;
    source_quote?: string | null;
    pillar_links: MemoryCardPillarLink[];
    duplicate_suggestions: MemoryCardDuplicateSuggestion[];
    created_at: string;
    updated_at: string;
};

export type MemoryCardsState = {
    token_id: string;
    pillars: Array<{ key: string; label: string; description: string }>;
    priority_weights: Record<string, number>;
    readiness: ReadinessState;
    cards: MemoryCard[];
};

export type TrainingDiagnostics = {
    token_id: string;
    readiness: ReadinessState;
    graph: {
        pillars: Array<{ key: string; label: string; description: string }>;
        edges: Array<{ left: string; right: string; points: number; fixed_cycle_edge: boolean }>;
        open_duplicate_suggestions: number;
    };
    latest_snapshot?: Record<string, unknown> | null;
};

export type TokenDetail = {
    participant: ParticipantToken;
    sessions: SessionSummary[];
    events: RawEvent[];
    analysis_runs: AnalysisRun[];
    evidence: BehavioralEvidence[];
    latest_harness_run?: TwinHarnessRun | null;
};

export type AnalysisRunDetail = AnalysisRun & {
    artifacts: AnalysisArtifact[];
    evidence: BehavioralEvidence[];
};

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers: {
            "Content-Type": "application/json",
            ...(init?.headers ?? {}),
        },
        cache: "no-store",
    });

    if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `API request failed: ${response.status}`);
    }

    return response.json() as Promise<T>;
}
