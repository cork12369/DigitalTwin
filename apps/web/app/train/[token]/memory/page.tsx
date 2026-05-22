import Link from "next/link";

import { API_SERVER_BASE_URL } from "@/lib/api-server";
import type { MemoryCardsState } from "@/lib/api";
import { MemoryClient } from "./memory-client";

type PageProps = {
    params: Promise<{ token: string }>;
};

async function getCards(token: string): Promise<{ state: MemoryCardsState | null; error: string | null }> {
    try {
        const response = await fetch(`${API_SERVER_BASE_URL}/api/training/cards`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
            cache: "no-store",
        });
        if (!response.ok) return { state: null, error: await response.text() };
        return { state: await response.json(), error: null };
    } catch {
        return { state: null, error: "API is not reachable." };
    }
}

export default async function MemoryPage({ params }: PageProps) {
    const { token } = await params;
    const { state, error } = await getCards(token);

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Memory Cards</span>
                    <h1>Review and rank what should matter later.</h1>
                    <p>Cards remain inactive for the twin phase until they are reviewed and prioritized.</p>
                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        <Link className="button secondary" href={`/train/${encodeURIComponent(token)}`}>Back to Chat</Link>
                        <Link className="button secondary" href={`/train/${encodeURIComponent(token)}/settings`}>Guide Settings</Link>
                    </div>
                </section>

                {state ? <MemoryClient token={token} initialState={state} /> : <section className="panel error">{error}</section>}
            </div>
        </main>
    );
}
