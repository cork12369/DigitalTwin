import Link from "next/link";

export default function HomePage() {
    return (
        <main className="page">
            <div className="container hero">
                <span className="eyebrow">Digital Twin Prototype</span>
                <h1>Behavioral mirror, not a questionnaire.</h1>
                <p>
                    A Zeabur-ready foundation for token-based participant scenarios, LangChain workflow instrumentation,
                    and an OpenClaw-inspired command center.
                </p>
                <div className="row" style={{ justifyContent: "flex-start" }}>
                    <Link className="button" href="/start">Initialize Twin</Link>
                    <Link className="button" href="/admin">Open Command Center</Link>
                    <Link className="button secondary" href="/admin/tokens">Manage Tokens</Link>
                </div>
            </div>
        </main>
    );
}
