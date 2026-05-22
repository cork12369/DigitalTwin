import Link from "next/link";

import { type AnalysisRun, type ErrorReport, type HealthResponse, type RawEvent } from "@/lib/api";
import { API_SERVER_BASE_URL, adminApiFetch } from "@/lib/api-server";

async function safeFetch<T>(path: string, fallback: T): Promise<T> {
    try {
        const response = path.startsWith("/api/admin")
            ? await adminApiFetch(path, { cache: "no-store" })
            : await fetch(`${API_SERVER_BASE_URL}${path}`, { cache: "no-store" });
        if (!response.ok) return fallback;
        return response.json();
    } catch {
        return fallback;
    }
}

function formatDate(value: string | null) {
    if (!value) return "—";
    return new Date(value).toLocaleString();
}

function statusTone(status?: string) {
    if (!status) return "muted";
    if (["ok", "completed", "configured"].includes(status)) return "status";
    if (["failed", "error"].includes(status)) return "error";
    return "status warning";
}

export default async function AdminDashboardPage() {
    const [apiHealth, dbHealth, langchainHealth, activity, runs, errors] = await Promise.all([
        safeFetch<HealthResponse>("/health", { status: "unreachable" }),
        safeFetch<HealthResponse>("/health/db", { status: "unreachable" }),
        safeFetch<HealthResponse>("/health/langchain", { status: "unreachable" }),
        safeFetch<RawEvent[]>("/api/admin/activity?limit=8", []),
        safeFetch<AnalysisRun[]>("/api/admin/analysis-runs?limit=8", []),
        safeFetch<ErrorReport[]>("/api/admin/errors?limit=8", []),
    ]);

    const healthCards = [
        { label: "Backend API", status: apiHealth.status, detail: String(apiHealth.service ?? "FastAPI service") },
        { label: "PostgreSQL event store", status: dbHealth.status, detail: String(dbHealth.database ?? "Database health") },
        { label: "LangChain workflow layer", status: langchainHealth.status, detail: String(langchainHealth.langchain ?? "Mock orchestration") },
        { label: "Model provider", status: String(langchainHealth.provider_status ?? "unknown"), detail: String(langchainHealth.model ?? "OpenRouter") },
        { label: "Raw activity feed", status: activity.length > 0 ? "ok" : "placeholder", detail: `${activity.length} recent events loaded` },
        { label: "Error inbox", status: errors.length > 0 ? "error" : "ok", detail: `${errors.length} unresolved errors` },
    ];

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Twin Command Center</span>
                    <h1>Launch, observe, and debug the twin runtime.</h1>
                    <p>
                        Phase 1 dashboard shell for service health, participant progress, LangChain runs, error inbox,
                        and memory/evidence review.
                    </p>
                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        <Link className="button" href="/admin/tokens">Generate Token</Link>
                        <Link className="button secondary" href="/admin/logout">Lock Admin</Link>
                        <Link className="button secondary" href="/">Back Home</Link>
                    </div>
                </section>

                <section className="grid">
                    {healthCards.map((card) => (
                        <article className="panel command-card" key={card.label}>
                            <div className="row card-header">
                                <h3>{card.label}</h3>
                                <span className={statusTone(card.status)}><span className="dot" />{card.status}</span>
                            </div>
                            <p className="muted">{card.detail}</p>
                        </article>
                    ))}
                </section>

                <section className="grid">
                    <article className="panel">
                        <h2>Live Activity Feed</h2>
                        <div className="stack">
                            {activity.length === 0 ? <p className="muted">No scenario activity captured yet.</p> : activity.map((event) => (
                                <div className="compact-panel" key={event.id}>
                                    <strong>{event.event_type}</strong>
                                    <div className="muted">{event.token_label ?? event.token_id}</div>
                                    <div className="muted">{formatDate(event.created_at)}</div>
                                </div>
                            ))}
                        </div>
                    </article>
                    <article className="panel">
                        <h2>Error Inbox</h2>
                        <div className="stack">
                            {errors.length === 0 ? <p className="muted">No unresolved errors.</p> : errors.map((error) => (
                                <div className="compact-panel" key={error.id}>
                                    <strong className="error">{error.summary}</strong>
                                    <div className="muted">{error.category} · {error.severity}</div>
                                    <div className="muted">{formatDate(error.created_at)}</div>
                                </div>
                            ))}
                        </div>
                    </article>
                    <article className="panel">
                        <h2>LangChain Runs</h2>
                        <div className="stack">
                            {runs.length === 0 ? <p className="muted">No analysis runs yet.</p> : runs.map((run) => (
                                <div className="compact-panel" key={run.id}>
                                    <div className="row">
                                        <strong>{run.analysis_type}</strong>
                                        <span className={statusTone(run.status)}><span className="dot" />{run.status}</span>
                                    </div>
                                    <div className="muted">{run.model_name}</div>
                                    <div className="muted">{formatDate(run.created_at)}</div>
                                    {run.output_summary && <p className="muted">{run.output_summary}</p>}
                                </div>
                            ))}
                        </div>
                    </article>
                </section>
            </div>
        </main>
    );
}
