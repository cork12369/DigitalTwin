import { API_SERVER_BASE_URL } from "@/lib/api-server";
import { ScenarioClient } from "./scenario-client";

type PageProps = {
    params: Promise<{ token: string }>;
};

async function validateToken(token: string) {
    try {
        const response = await fetch(`${API_SERVER_BASE_URL}/api/tokens/validate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
            cache: "no-store",
        });
        if (!response.ok) return { valid: false, message: "Token validation failed." };
        return response.json();
    } catch {
        return { valid: false, message: "API is not reachable." };
    }
}

async function startSession(token: string) {
    const response = await fetch(`${API_SERVER_BASE_URL}/api/sessions/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
        cache: "no-store",
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
}

export default async function PlayPage({ params }: PageProps) {
    const { token } = await params;
    const validation = await validateToken(token);
    const sessionState = validation.valid ? await startSession(token) : null;

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Participant Scenario</span>
                    <h1>{validation.valid ? "Your session is ready." : "This invite needs attention."}</h1>
                    <p>{validation.message}</p>
                </section>

                <section className="panel stack">
                    <h2>Adaptive Scenario</h2>
                    <p className="muted">Answer each prompt as it appears. The next one is tailored from your previous answer.</p>
                    {validation.valid && <code>Session ID: {validation.session_id}</code>}
                </section>

                {sessionState && <ScenarioClient token={token} initialState={sessionState} />}
            </div>
        </main>
    );
}
