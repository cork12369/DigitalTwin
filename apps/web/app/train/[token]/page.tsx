import Link from "next/link";

import { API_SERVER_BASE_URL } from "@/lib/api-server";
import type { TrainingState } from "@/lib/api";
import { TrainingClient } from "./training-client";

type PageProps = {
    params: Promise<{ token: string }>;
};

async function startTraining(token: string): Promise<{ state: TrainingState | null; error: string | null }> {
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

export default async function TrainPage({ params }: PageProps) {
    const { token } = await params;
    const { state, error } = await startTraining(token);

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Initialization Chat</span>
                    <h1>Build the raw material for your twin.</h1>
                    <p>
                        Chat naturally with the initialization guide. Draft memory cards are created from the conversation,
                        but reviewed cards stay inactive until the later twin phase.
                    </p>
                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        <Link className="button secondary" href={`/play/${encodeURIComponent(token)}`}>Back to Quiz</Link>
                        <Link className="button secondary" href={`/train/${encodeURIComponent(token)}/memory`}>Memory Cards</Link>
                        <Link className="button secondary" href={`/train/${encodeURIComponent(token)}/settings`}>Guide Settings</Link>
                    </div>
                </section>

                {state ? (
                    <TrainingClient token={token} initialState={state} />
                ) : (
                    <section className="panel error stack">
                        <h2>Training is not ready.</h2>
                        <p>{error ?? "Finish the adaptive quiz before opening initialization chat."}</p>
                        <Link className="button" href={`/play/${encodeURIComponent(token)}`}>Open Quiz</Link>
                    </section>
                )}
            </div>
        </main>
    );
}
