import Link from "next/link";

import { API_BASE_URL } from "@/lib/api";
import { CreateTokenForm } from "./create-token-form";
import { TokenActions } from "./token-actions";

type ParticipantToken = {
    id: string;
    label: string;
    status: string;
    created_at: string;
    expires_at: string | null;
    first_used_at: string | null;
    last_seen_at: string | null;
    completed_at: string | null;
    current_step: string | null;
    session_status: string | null;
    event_count: number;
};

function formatDate(value: string | null) {
    if (!value) return "—";
    return new Date(value).toLocaleString();
}

async function getTokens(): Promise<ParticipantToken[]> {
    try {
        const response = await fetch(`${API_BASE_URL}/api/admin/tokens/summary`, { cache: "no-store" });
        if (!response.ok) return [];
        return response.json();
    } catch {
        return [];
    }
}

export default async function TokenAdminPage() {
    const tokens = await getTokens();

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Token Management</span>
                    <h1>Admin-generated participant access.</h1>
                    <p>
                        Create personal invite tokens, monitor status, and keep scenario data mapped to each participant.
                    </p>
                    <Link className="button secondary" href="/admin">Back to Dashboard</Link>
                </section>

                <section className="panel stack">
                    <h2>Create Token</h2>
                    <p className="muted">Generate a personal invite link for a participant.</p>
                    <CreateTokenForm />
                </section>

                <section className="panel stack">
                    <h2>Existing Tokens</h2>
                    {tokens.length === 0 ? (
                        <p className="muted">No tokens found yet, or API is not reachable.</p>
                    ) : (
                        tokens.map((token) => (
                            <div className="panel compact-panel stack" key={token.id}>
                                <div className="row">
                                    <div>
                                        <strong>{token.label}</strong>
                                        <div className="muted">{token.id}</div>
                                        <div className="muted">Created: {formatDate(token.created_at)}</div>
                                        <div className="muted">Last seen: {formatDate(token.last_seen_at)}</div>
                                        <div className="muted">Session: {token.session_status ?? "not started"}</div>
                                        <div className="muted">Current step: {token.current_step ?? "—"}</div>
                                        <div className="muted">Events captured: {token.event_count}</div>
                                    </div>
                                    <span className="status"><span className="dot" />{token.status}</span>
                                </div>
                                <TokenActions tokenId={token.id} disabled={token.status === "revoked"} />
                            </div>
                        ))
                    )}
                </section>
            </div>
        </main>
    );
}