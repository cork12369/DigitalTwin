import Link from "next/link";

import { analyzeTokenAction } from "../actions";
import { type AnalysisRunDetail, type TokenDetail } from "@/lib/api";
import { adminApiFetch } from "@/lib/api-server";

type PageProps = {
    params: Promise<{ tokenId: string }>;
};

function formatDate(value: string | null) {
    if (!value) return "—";
    return new Date(value).toLocaleString();
}

async function getTokenDetail(tokenId: string): Promise<TokenDetail | null> {
    try {
        const response = await adminApiFetch(`/api/admin/tokens/${tokenId}/detail`, { cache: "no-store" });
        if (!response.ok) return null;
        return response.json();
    } catch {
        return null;
    }
}

async function getRunDetail(runId: string | undefined): Promise<AnalysisRunDetail | null> {
    if (!runId) return null;
    try {
        const response = await adminApiFetch(`/api/admin/analysis-runs/${runId}`, { cache: "no-store" });
        if (!response.ok) return null;
        return response.json();
    } catch {
        return null;
    }
}

export default async function TokenDetailPage({ params }: PageProps) {
    const { tokenId } = await params;
    const detail = await getTokenDetail(tokenId);
    const latestRun = detail?.analysis_runs[0];
    const latestRunDetail = await getRunDetail(latestRun?.id);

    if (!detail) {
        return (
            <main className="page">
                <div className="container stack">
                    <Link className="button secondary" href="/admin/tokens">Back to Tokens</Link>
                    <section className="panel error">Token detail was not found or API is unreachable.</section>
                </div>
            </main>
        );
    }

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Evidence Browser</span>
                    <h1>{detail.participant.label}</h1>
                    <p>
                        Inspect raw scenario events, reliability-first evidence, analysis runs, and graph update proposals for this participant token.
                    </p>
                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        <Link className="button secondary" href="/admin/tokens">Back to Tokens</Link>
                        <Link className="button secondary" href="/admin/logout">Lock Admin</Link>
                        <form action={analyzeTokenAction}>
                            <input type="hidden" name="tokenId" value={tokenId} />
                            <button className="button" type="submit">Run Analysis</button>
                        </form>
                    </div>
                </section>

                <section className="grid">
                    <article className="panel">
                        <h2>Status</h2>
                        <div className="status"><span className="dot" />{detail.participant.status}</div>
                        <p className="muted">Session: {detail.participant.session_status ?? "not started"}</p>
                        <p className="muted">Current step: {detail.participant.current_step ?? "—"}</p>
                    </article>
                    <article className="panel">
                        <h2>Captured Data</h2>
                        <p className="muted">Events: {detail.participant.event_count ?? detail.events.length}</p>
                        <p className="muted">Evidence: {detail.participant.evidence_count ?? detail.evidence.length}</p>
                        <p className="muted">Analysis runs: {detail.analysis_runs.length}</p>
                    </article>
                    <article className="panel">
                        <h2>Timeline</h2>
                        <p className="muted">Created: {formatDate(detail.participant.created_at)}</p>
                        <p className="muted">Last seen: {formatDate(detail.participant.last_seen_at)}</p>
                        <p className="muted">Completed: {formatDate(detail.participant.completed_at)}</p>
                    </article>
                </section>

                <section className="grid">
                    <article className="panel stack">
                        <h2>Behavioral Evidence</h2>
                        {detail.evidence.length === 0 ? <p className="muted">No evidence extracted yet. Run analysis after events are captured.</p> : detail.evidence.map((item) => (
                            <div className="compact-panel" key={item.id}>
                                <div className="row">
                                    <strong>{item.evidence_type}</strong>
                                    <span className="status"><span className="dot" />{item.confidence}</span>
                                </div>
                                <p>{item.summary}</p>
                                {item.supporting_quote && <blockquote>{item.supporting_quote}</blockquote>}
                                <div className="muted">Sources: {item.source_event_ids.join(", ")}</div>
                            </div>
                        ))}
                    </article>

                    <article className="panel stack">
                        <h2>Analysis Runs</h2>
                        {detail.analysis_runs.length === 0 ? <p className="muted">No analysis runs yet.</p> : detail.analysis_runs.map((run) => (
                            <div className="compact-panel" key={run.id}>
                                <div className="row">
                                    <strong>{run.status}</strong>
                                    <span className="muted">{formatDate(run.created_at)}</span>
                                </div>
                                <div className="muted">{run.model_name} · {run.prompt_version}</div>
                                {run.output_summary && <p className="muted">{run.output_summary}</p>}
                                {run.error_summary && <p className="error">{run.error_summary}</p>}
                            </div>
                        ))}
                    </article>
                </section>

                <section className="grid">
                    <article className="panel stack">
                        <h2>Latest Run Artifacts</h2>
                        {!latestRunDetail ? <p className="muted">Run analysis to create artifacts.</p> : latestRunDetail.artifacts.map((artifact) => (
                            <div className="compact-panel" key={artifact.id}>
                                <div className="row">
                                    <strong>{artifact.artifact_type}</strong>
                                    <span className="status"><span className="dot" />{artifact.confidence}</span>
                                </div>
                                <div className="muted">Validation: {artifact.validation_status}</div>
                                <pre>{JSON.stringify(artifact.payload, null, 2)}</pre>
                            </div>
                        ))}
                    </article>

                    <article className="panel stack">
                        <h2>Raw Events</h2>
                        {detail.events.length === 0 ? <p className="muted">No events captured yet.</p> : detail.events.map((event) => (
                            <div className="compact-panel" key={event.id}>
                                <div className="row">
                                    <strong>{event.event_type}</strong>
                                    <span className="muted">{formatDate(event.created_at)}</span>
                                </div>
                                <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                            </div>
                        ))}
                    </article>
                </section>
            </div>
        </main>
    );
}
