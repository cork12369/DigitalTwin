import Link from "next/link";

const healthCards = [
    "Backend API",
    "LangChain workflow layer",
    "PostgreSQL event store",
    "Value graph store",
    "Model provider",
    "Frontend",
];

export default function AdminDashboardPage() {
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
                        <Link className="button secondary" href="/">Back Home</Link>
                    </div>
                </section>

                <section className="grid">
                    {healthCards.map((label) => (
                        <article className="panel" key={label}>
                            <div className="row">
                                <h3>{label}</h3>
                                <span className="status"><span className="dot" />Ready</span>
                            </div>
                            <p className="muted">Health endpoint wiring starts in Phase 1; live status polling comes next.</p>
                        </article>
                    ))}
                </section>

                <section className="grid">
                    <article className="panel">
                        <h2>Live Activity Feed</h2>
                        <p className="muted">Probe sessions, duels, corrections, and value-graph updates will stream here.</p>
                    </article>
                    <article className="panel">
                        <h2>Error Inbox</h2>
                        <p className="muted">Workflow, provider, validation, graph, memory, and infrastructure errors will appear here.</p>
                    </article>
                    <article className="panel">
                        <h2>LangChain Runs</h2>
                        <p className="muted">Run status, duration, retries, inputs, outputs, and failure reasons will be tracked here.</p>
                    </article>
                </section>
            </div>
        </main>
    );
}