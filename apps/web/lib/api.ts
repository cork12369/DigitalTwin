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

export type TokenDetail = {
    participant: ParticipantToken;
    sessions: SessionSummary[];
    events: RawEvent[];
    analysis_runs: AnalysisRun[];
    evidence: BehavioralEvidence[];
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
