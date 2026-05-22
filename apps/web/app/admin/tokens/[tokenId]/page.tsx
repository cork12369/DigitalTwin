import Link from "next/link";

import { analyzeTokenAction } from "../actions";
import { HarnessRunButton } from "./harness-run-button";
import { type AnalysisRunDetail, type TokenDetail, type TrainingDiagnostics, type TwinHarnessRunDetail, type TwinHarnessScore } from "@/lib/api";
import { adminApiFetch } from "@/lib/api-server";

type PageProps = {
    params: Promise<{ tokenId: string }>;
};

function formatDate(value: string | null) {
    if (!value) return "--";
    return new Date(value).toLocaleString();
}

function formatMetric(value: number | null | undefined) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "0.000";
    return value.toFixed(3);
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

async function getTrainingDiagnostics(tokenId: string): Promise<TrainingDiagnostics | null> {
    try {
        const response = await adminApiFetch(`/api/admin/tokens/${tokenId}/training-diagnostics`, { cache: "no-store" });
        if (!response.ok) return null;
        return response.json();
    } catch {
        return null;
    }
}

async function getHarnessRunDetail(runId: string | undefined): Promise<TwinHarnessRunDetail | null> {
    if (!runId) return null;
    try {
        const response = await adminApiFetch(`/api/admin/harness/runs/${runId}`, { cache: "no-store" });
        if (!response.ok) return null;
        return response.json();
    } catch {
        return null;
    }
}

type ScoreSummary = {
    key: string;
    label: string;
    metricType: string;
    averageLift: number;
    averageBits: number;
    averageKl: number;
    verdict: string;
    count: number;
};

function summarizeScores(scores: TwinHarnessScore[], sourceType: string, metricType?: string): ScoreSummary[] {
    const grouped = new Map<string, {
        label: string;
        metricType: string;
        lift: number;
        bits: number;
        kl: number;
        count: number;
        verdicts: Record<string, number>;
    }>();

    for (const score of scores) {
        if (score.source_type !== sourceType) continue;
        if (metricType && score.metric_type !== metricType) continue;
        const key = `${score.source_type}:${score.source_id ?? "unknown"}:${score.metric_type}`;
        const existing = grouped.get(key) ?? {
            label: score.source_label ?? score.source_id ?? "Unknown source",
            metricType: score.metric_type,
            lift: 0,
            bits: 0,
            kl: 0,
            count: 0,
            verdicts: {},
        };
        existing.lift += score.lift;
        existing.bits += score.information_gain_bits;
        existing.kl += score.kl_divergence;
        existing.count += 1;
        existing.verdicts[score.verdict] = (existing.verdicts[score.verdict] ?? 0) + 1;
        grouped.set(key, existing);
    }

    return [...grouped.entries()].map(([key, value]) => ({
        key,
        label: value.label,
        metricType: value.metricType,
        averageLift: value.lift / value.count,
        averageBits: value.bits / value.count,
        averageKl: value.kl / value.count,
        verdict: Object.entries(value.verdicts).sort((left, right) => right[1] - left[1])[0]?.[0] ?? "mixed",
        count: value.count,
    }));
}

function ScoreList({ title, scores, empty }: { title: string; scores: ScoreSummary[]; empty: string }) {
    return (
        <div className="compact-panel stack">
            <h3>{title}</h3>
            {scores.length === 0 ? <p className="muted">{empty}</p> : scores.slice(0, 6).map((score) => (
                <div className="compact-panel" key={score.key}>
                    <div className="row">
                        <strong>{score.label}</strong>
                        <span className="status"><span className="dot" />{score.verdict}</span>
                    </div>
                    <div className="muted">
                        {score.metricType} | lift {formatMetric(score.averageLift)} nats | {formatMetric(score.averageBits)} bits | KL {formatMetric(score.averageKl)} | n={score.count}
                    </div>
                </div>
            ))}
        </div>
    );
}

function HarnessDiagnostics({ run }: { run: TwinHarnessRunDetail | null }) {
    if (!run) {
        return <p className="muted">No diagnostics harness run yet.</p>;
    }

    const aggregate = run.aggregate_metrics ?? {};
    const cardRanking = summarizeScores(run.scores, "memory_card", "isolated_lift")
        .sort((left, right) => right.averageLift - left.averageLift);
    const questionnaireRanking = summarizeScores(run.scores, "question_event", "isolated_lift")
        .sort((left, right) => right.averageLift - left.averageLift);
    const allSummaries = [
        ...summarizeScores(run.scores, "memory_card"),
        ...summarizeScores(run.scores, "question_event"),
    ];
    const inertSources = allSummaries
        .filter((score) => score.verdict === "zero_impact")
        .sort((left, right) => Math.abs(left.averageLift) - Math.abs(right.averageLift));
    const negativeSources = allSummaries
        .filter((score) => score.verdict === "negative_drift")
        .sort((left, right) => left.averageLift - right.averageLift);

    return (
        <div className="stack">
            <div className="grid">
                <article className="compact-panel">
                    <h3>Latest Run</h3>
                    <div className="status"><span className="dot" />{run.status}</div>
                    <p className="muted">Trigger: {run.trigger_reason}</p>
                    <p className="muted">Model: {run.model_name || "not configured"}</p>
                    <p className="muted">Created: {formatDate(run.created_at)}</p>
                </article>
                <article className="compact-panel">
                    <h3>Coverage</h3>
                    <p className="muted">Cases: {String(aggregate.case_count ?? run.cases.length)}</p>
                    <p className="muted">Scores: {String(aggregate.score_count ?? run.scores.length)}</p>
                    <p className="muted">Skipped targets: {String(aggregate.skipped_target_count ?? 0)}</p>
                </article>
                <article className="compact-panel">
                    <h3>Aggregate</h3>
                    <p className="muted">Average lift: {formatMetric(Number(aggregate.average_lift ?? 0))}</p>
                    <p className="muted">Average KL: {formatMetric(Number(aggregate.average_kl_divergence ?? 0))}</p>
                    <p className="muted">Prompt: {run.prompt_version}</p>
                </article>
            </div>

            {run.status === "unsupported_model" && (
                <div className="context-panel">
                    <strong>Unsupported model/logprobs</strong>
                    <p className="muted">
                        {run.error_summary ?? "Configured model did not return usable logprobs. Switch OPENROUTER_MODEL to a chat model/provider with logprobs and top_logprobs support."}
                    </p>
                </div>
            )}
            {run.error_summary && run.status !== "unsupported_model" && <p className="error">{run.error_summary}</p>}
            {run.output_summary && <p className="muted">{run.output_summary}</p>}

            <div className="grid">
                <ScoreList title="Card Lift Ranking" scores={cardRanking} empty="No reviewed memory card scores yet." />
                <ScoreList title="Questionnaire Lift Ranking" scores={questionnaireRanking} empty="No questionnaire scores yet." />
            </div>
            <div className="grid">
                <ScoreList title="Negative Drift" scores={negativeSources} empty="No negative-drift sources in the latest run." />
                <ScoreList title="Inert Sources" scores={inertSources} empty="No near-zero sources in the latest run." />
            </div>
        </div>
    );
}

export default async function TokenDetailPage({ params }: PageProps) {
    const { tokenId } = await params;
    const detail = await getTokenDetail(tokenId);
    const latestRun = detail?.analysis_runs[0];
    const latestRunDetail = await getRunDetail(latestRun?.id);
    const latestHarnessDetail = await getHarnessRunDetail(detail?.latest_harness_run?.id);
    const trainingDiagnostics = detail ? await getTrainingDiagnostics(tokenId) : null;

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
                        <HarnessRunButton tokenId={tokenId} />
                    </div>
                </section>

                <section className="grid">
                    <article className="panel">
                        <h2>Status</h2>
                        <div className="status"><span className="dot" />{detail.participant.status}</div>
                        <p className="muted">Session: {detail.participant.session_status ?? "not started"}</p>
                        <p className="muted">Current step: {detail.participant.current_step ?? "--"}</p>
                        <p className="muted">Initialization: {detail.participant.initialization_status ?? "not_started"}</p>
                    </article>
                    <article className="panel">
                        <h2>Captured Data</h2>
                        <p className="muted">Events: {detail.participant.event_count ?? detail.events.length}</p>
                        <p className="muted">Evidence: {detail.participant.evidence_count ?? detail.evidence.length}</p>
                        <p className="muted">Analysis runs: {detail.analysis_runs.length}</p>
                        <p className="muted">Harness: {detail.latest_harness_run?.status ?? "not run"}</p>
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
                        <h2>Initialization Coverage</h2>
                        {!trainingDiagnostics ? <p className="muted">No training diagnostics yet.</p> : (
                            <>
                                <div className="status"><span className="dot" />{trainingDiagnostics.readiness.overall_percent}% ready</div>
                                <progress value={trainingDiagnostics.readiness.overall_percent} max={100} />
                                {trainingDiagnostics.readiness.pillars.map((pillar) => (
                                    <div className="pillar-meter" key={pillar.key}>
                                        <div className="row">
                                            <strong>{pillar.label}</strong>
                                            <span className="muted">{pillar.score}/{pillar.target}</span>
                                        </div>
                                        <progress value={pillar.percent} max={100} />
                                    </div>
                                ))}
                            </>
                        )}
                    </article>

                    <article className="panel stack">
                        <h2>Advanced Graph Edges</h2>
                        {!trainingDiagnostics ? <p className="muted">No edge diagnostics yet.</p> : trainingDiagnostics.graph.edges.map((edge) => (
                            <div className="compact-panel" key={`${edge.left}-${edge.right}`}>
                                <strong>{edge.left} - {edge.right}</strong>
                                <div className="muted">Points: {edge.points} · {edge.fixed_cycle_edge ? "cycle" : "emergent"}</div>
                            </div>
                        ))}
                    </article>
                </section>

                <section className="panel stack">
                    <div className="row">
                        <div>
                            <h2>Memory + Questionnaire Harness</h2>
                            <p className="muted">Admin-only diagnostics for source lift, ablation, inert signals, and negative drift.</p>
                        </div>
                        <HarnessRunButton tokenId={tokenId} />
                    </div>
                    <HarnessDiagnostics run={latestHarnessDetail} />
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
