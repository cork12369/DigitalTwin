"use client";

import { useMemo, useState, useTransition } from "react";

import { API_BASE_URL } from "@/lib/api";

type ScenarioStep = {
    id: string;
    type: string;
    title: string;
    prompt: string;
    options?: string[] | null;
};

type SessionState = {
    session_id: string;
    token_id: string;
    token_status: string;
    session_status: string;
    current_step: string;
    steps: ScenarioStep[];
    completed_step_ids: string[];
    event_count: number;
};

export function ScenarioClient({ token, initialState }: { token: string; initialState: SessionState }) {
    const [state, setState] = useState(initialState);
    const [selected, setSelected] = useState("");
    const [text, setText] = useState("");
    const [ranked, setRanked] = useState<string[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [isPending, startTransition] = useTransition();

    const currentStep = useMemo(
        () => state.steps.find((step) => step.id === state.current_step) ?? null,
        [state.current_step, state.steps],
    );

    const progress = Math.round((state.completed_step_ids.length / state.steps.length) * 100);

    function resetInputs() {
        setSelected("");
        setText("");
        setRanked([]);
    }

    async function refreshState(sessionId = state.session_id) {
        const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}/state`, { cache: "no-store" });
        if (!response.ok) throw new Error(await response.text());
        setState(await response.json());
    }

    function buildAnswer(step: ScenarioStep) {
        if (step.type === "intro") return { acknowledged: true };
        if (step.type === "triad" || step.type === "duel") return { selected_option: selected };
        if (step.type === "context_flip" || step.type === "correction") return { text };
        if (step.type === "twin_rank") return { ranked_options: ranked };
        return { selected_option: selected, text };
    }

    function canSubmit(step: ScenarioStep) {
        if (step.type === "intro") return true;
        if (step.type === "triad" || step.type === "duel") return Boolean(selected);
        if (step.type === "context_flip" || step.type === "correction") return text.trim().length > 0;
        if (step.type === "twin_rank") return ranked.length === (step.options?.length ?? 0);
        return true;
    }

    function submitStep() {
        if (!currentStep) return;
        setError(null);
        startTransition(async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/api/sessions/${state.session_id}/answer`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        token,
                        step_id: currentStep.id,
                        step_type: currentStep.type,
                        answer: buildAnswer(currentStep),
                    }),
                    cache: "no-store",
                });
                if (!response.ok) throw new Error(await response.text());
                resetInputs();
                await refreshState();
            } catch (submitError) {
                setError(submitError instanceof Error ? submitError.message : "Unable to save answer.");
            }
        });
    }

    function completeScenario() {
        setError(null);
        startTransition(async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/api/sessions/${state.session_id}/complete`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token }),
                    cache: "no-store",
                });
                if (!response.ok) throw new Error(await response.text());
                setState(await response.json());
            } catch (completeError) {
                setError(completeError instanceof Error ? completeError.message : "Unable to complete scenario.");
            }
        });
    }

    function toggleRank(option: string) {
        setRanked((current) => current.includes(option) ? current.filter((item) => item !== option) : [...current, option]);
    }

    if (state.current_step === "complete" || state.session_status === "completed") {
        return (
            <section className="panel stack">
                <span className="eyebrow">Scenario Complete</span>
                <h2>Your behavioral mirror session is complete.</h2>
                <p className="muted">Your answers were saved as raw behavioral evidence for this token.</p>
                <div className="status"><span className="dot" />{state.event_count} events captured</div>
            </section>
        );
    }

    if (!currentStep) {
        return <section className="panel error">Unable to find current step: {state.current_step}</section>;
    }

    return (
        <section className="panel stack">
            <div className="row">
                <span className="eyebrow">Step {state.completed_step_ids.length + 1} of {state.steps.length}</span>
                <span className="status"><span className="dot" />{progress}%</span>
            </div>
            <progress value={state.completed_step_ids.length} max={state.steps.length} />
            <h2>{currentStep.title}</h2>
            <p className="muted">{currentStep.prompt}</p>

            {(currentStep.type === "triad" || currentStep.type === "duel") && currentStep.options && (
                <div className="stack">
                    {currentStep.options.map((option) => (
                        <button
                            className={`choice ${selected === option ? "selected" : ""}`}
                            key={option}
                            type="button"
                            onClick={() => setSelected(option)}
                        >
                            {option}
                        </button>
                    ))}
                </div>
            )}

            {(currentStep.type === "context_flip" || currentStep.type === "correction") && (
                <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Write your reasoning here..." />
            )}

            {currentStep.type === "twin_rank" && currentStep.options && (
                <div className="stack">
                    <p className="muted">Click options in order from closest to least close.</p>
                    {currentStep.options.map((option) => (
                        <button className={`choice ${ranked.includes(option) ? "selected" : ""}`} key={option} type="button" onClick={() => toggleRank(option)}>
                            {ranked.includes(option) ? `${ranked.indexOf(option) + 1}. ` : ""}{option}
                        </button>
                    ))}
                </div>
            )}

            {error && <p className="error">{error}</p>}

            {state.completed_step_ids.length >= state.steps.length ? (
                <button className="button" type="button" onClick={completeScenario} disabled={isPending}>
                    Complete Scenario
                </button>
            ) : (
                <button className="button" type="button" onClick={submitStep} disabled={isPending || !canSubmit(currentStep)}>
                    {isPending ? "Saving..." : currentStep.type === "intro" ? "Begin" : "Save and Continue"}
                </button>
            )}
        </section>
    );
}