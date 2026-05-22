import Link from "next/link";

import { API_SERVER_BASE_URL } from "@/lib/api-server";
import type { TrainingState } from "@/lib/api";
import { GuideSettingsClient } from "./settings-client";

type PageProps = {
    params: Promise<{ token: string }>;
};

async function getTrainingState(token: string): Promise<{ state: TrainingState | null; error: string | null }> {
    try {
        const response = await fetch(`${API_SERVER_BASE_URL}/api/training/start`, {
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

export default async function GuideSettingsPage({ params }: PageProps) {
    const { token } = await params;
    const { state, error } = await getTrainingState(token);

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Guide Settings</span>
                    <h1>Tune the initialization guide.</h1>
                    <p>Optional style and topic preferences shape the guide's voice without changing the extraction rules.</p>
                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        <Link className="button secondary" href={`/train/${encodeURIComponent(token)}`}>Back to Chat</Link>
                        <Link className="button secondary" href={`/train/${encodeURIComponent(token)}/memory`}>Memory Cards</Link>
                    </div>
                </section>

                {state ? <GuideSettingsClient token={token} initialState={state} /> : <section className="panel error">{error}</section>}
            </div>
        </main>
    );
}
