import Link from "next/link";

import { type ParticipantToken } from "@/lib/api";
import { adminApiFetch } from "@/lib/api-server";
import { AuthKeyReveal } from "./auth-key-reveal";
import { CreateTokenForm } from "./create-token-form";
import { TokenActions } from "./token-actions";

type PageProps = {
    searchParams?: Promise<{ status?: string }>;
};

const STATUS_FILTERS = [
    { label: "All", value: "all" },
    { label: "Generated", value: "generated" },
    { label: "Active", value: "active" },
    { label: "In progress", value: "in_progress" },
    { label: "Completed", value: "completed" },
    { label: "Revoked", value: "revoked" },
    { label: "Expired", value: "expired" },
    { label: "Errored", value: "errored" },
    { label: "Reset", value: "reset" },
];

function formatDate(value: string | null) {
    if (!value) return "-";
    return new Date(value).toLocaleString();
}

async function getTokens(): Promise<ParticipantToken[]> {
    try {
        const response = await adminApiFetch("/api/admin/tokens/summary", { cache: "no-store" });
        if (!response.ok) return [];
        return response.json();
    } catch {
        return [];
    }
}

function filterTokens(tokens: ParticipantToken[], status: string) {
    if (status === "all") return tokens;
    return tokens.filter((token) => token.status === status);
}

export default async function TokenAdminPage({ searchParams }: PageProps) {
    const params = await searchParams;
    const tokens = await getTokens();
    const requestedStatus = params?.status ?? "all";
    const activeStatus = STATUS_FILTERS.some((filter) => filter.value === requestedStatus)
        ? requestedStatus
        : "all";
    const visibleTokens = filterTokens(tokens, activeStatus);
    const counts = STATUS_FILTERS.reduce<Record<string, number>>((current, filter) => {
        current[filter.value] = filter.value === "all"
            ? tokens.length
            : tokens.filter((token) => token.status === filter.value).length;
        return current;
    }, {});

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Token Management</span>
                    <h1>Admin-generated participant access.</h1>
                    <p>
                        Create personal invite tokens, monitor status, and keep scenario data mapped to each participant.
                    </p>
                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        <Link className="button secondary" href="/admin">Back to Dashboard</Link>
                        <Link className="button secondary" href="/admin/logout">Lock Admin</Link>
                        <Link className="button secondary" href="/start">Participant Start Page</Link>
                    </div>
                </section>

                <section className="panel stack">
                    <h2>Create Token</h2>
                    <p className="muted">Generate a personal invite link for a participant.</p>
                    <CreateTokenForm />
                </section>

                <section className="panel stack">
                    <div className="row">
                        <div>
                            <h2>Existing Tokens</h2>
                            <p className="muted">Showing {visibleTokens.length} of {tokens.length} tokens.</p>
                        </div>
                        <span className="status"><span className="dot" />{activeStatus}</span>
                    </div>

                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        {STATUS_FILTERS.map((filter) => {
                            const href = filter.value === "all" ? "/admin/tokens" : `/admin/tokens?status=${filter.value}`;
                            const selected = filter.value === activeStatus;
                            return (
                                <Link className={`button ${selected ? "" : "secondary"}`} href={href} key={filter.value}>
                                    {filter.label} ({counts[filter.value] ?? 0})
                                </Link>
                            );
                        })}
                    </div>

                    {tokens.length === 0 ? (
                        <p className="muted">No tokens found yet, or API is not reachable.</p>
                    ) : visibleTokens.length === 0 ? (
                        <p className="muted">No tokens match this status.</p>
                    ) : (
                        visibleTokens.map((token) => (
                            <div className="panel compact-panel stack" key={token.id}>
                                <div className="row">
                                    <div>
                                        <strong>{token.label}</strong>
                                        <div className="muted">{token.id}</div>
                                        <div className="muted">Created: {formatDate(token.created_at)}</div>
                                        <div className="muted">Last seen: {formatDate(token.last_seen_at)}</div>
                                        <div className="muted">Session: {token.session_status ?? "not started"}</div>
                                        <div className="muted">Current step: {token.current_step ?? "-"}</div>
                                        <div className="muted">Events captured: {token.event_count ?? 0}</div>
                                        <div className="muted">Evidence: {token.evidence_count ?? 0}</div>
                                        <div className="muted">Latest analysis: {token.latest_analysis_status ?? "not run"}</div>
                                    </div>
                                    <span className="status"><span className="dot" />{token.status}</span>
                                </div>
                                <AuthKeyReveal authKey={token.auth_key} inviteUrl={token.invite_url} />
                                <Link className="button secondary" href={`/admin/tokens/${token.id}`}>Open Evidence Browser</Link>
                                <TokenActions tokenId={token.id} status={token.status} />
                            </div>
                        ))
                    )}
                </section>
            </div>
        </main>
    );
}
