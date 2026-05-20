"use client";

import { useMemo, useState, useTransition } from "react";

import { API_BASE_URL } from "@/lib/api";

type ScenarioStep = {
    id: string;
    type: string;
    title: string;
    prompt: string;
    options?: string[] | null;
    context_title?: string | null;
    context_items?: string[] | null;
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
    adaptive_question_count: number;
    max_adaptive_questions: number;
    scenario_generation_status?: string | null;
    scenario_generation_message?: string | null;
};

export function ScenarioClient({ token, initialState }: { token: string; initialState: SessionState }) {
    const [state, setState] = useState(initialState);
    const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
    const [text, setText] = useState("");
    const [cvFile, setCvFile] = useState<File | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [isPending, startTransition] = useTransition();

    const currentStep = useMemo(
        () => state.steps.find((step) => step.id === state.current_step) ?? null,
        [state.current_step, state.steps],
    );

    const progressValue = Math.min(state.adaptive_question_count, state.max_adaptive_questions);
    const progressPercent = Math.round((progressValue / state.max_adaptive_questions) * 100);
    const isChoiceStep = currentStep?.type === "triad" || currentStep?.type === "duel";

    function resetInputs() {
        setSelectedIndex(null);
        setText("");
        setCvFile(null);
    }

    async function refreshState(sessionId = state.session_id) {
        const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}/state`, { cache: "no-store" });
        if (!response.ok) throw new Error(await response.text());
        setState(await response.json());
    }

    function buildAnswer(step: ScenarioStep) {
        if (step.type === "onboarding") return { user_profile: text.trim() };
        if ((step.type === "triad" || step.type === "duel") && selectedIndex !== null) {
            return {
                selected_index: selectedIndex,
                selected_option: step.options?.[selectedIndex] ?? "",
            };
        }
        return {};
    }

    function canSubmit(step: ScenarioStep) {
        if (step.type === "onboarding") return Boolean(cvFile) || text.trim().length >= 2;
        if (step.type === "triad" || step.type === "duel") return selectedIndex !== null;
        return true;
    }

    async function submitCvProfile() {
        if (!cvFile) return;
        const formData = new FormData();
        formData.append("token", token);
        formData.append("file", cvFile);

        const response = await fetch(`${API_BASE_URL}/api/sessions/${state.session_id}/profile/cv`, {
            method: "POST",
            body: formData,
            cache: "no-store",
        });
        if (!response.ok) throw new Error(await response.text());
    }

    function submitStep() {
        if (!currentStep) return;
        setError(null);
        startTransition(async () => {
            try {
                if (currentStep.type === "onboarding" && cvFile) {
                    await submitCvProfile();
                } else {
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
                }
                resetInputs();
                await refreshState();
            } catch (submitError) {
                setError(submitError instanceof Error ? submitError.message : "Unable to save answer.");
            }
        });
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
                <span className="eyebrow">
                    {currentStep.type === "onboarding"
                        ? "Profile setup"
                        : `Question ${state.adaptive_question_count + 1} of up to ${state.max_adaptive_questions}`}
                </span>
                <span className="status"><span className="dot" />{progressPercent}%</span>
            </div>
            <progress value={progressValue} max={state.max_adaptive_questions} />
            <h2>{currentStep.title}</h2>
            <p className="muted">{currentStep.prompt}</p>

            {currentStep.context_items && currentStep.context_items.length > 0 && (
                <div className="context-panel stack">
                    <strong>{currentStep.context_title ?? "Context"}</strong>
                    <ul>
                        {currentStep.context_items.map((item) => (
                            <li key={item}>{item}</li>
                        ))}
                    </ul>
                </div>
            )}

            {currentStep.type === "onboarding" && (
                <div className="stack">
                    <textarea
                        value={text}
                        onChange={(event) => setText(event.target.value)}
                        placeholder="Background, hobbies, work, current project..."
                        disabled={Boolean(cvFile)}
                    />
                    <div className="context-panel stack">
                        <strong>Use a CV instead</strong>
                        <input
                            accept="application/pdf,.pdf"
                            onChange={(event) => setCvFile(event.target.files?.[0] ?? null)}
                            type="file"
                        />
                        {cvFile && <p className="muted">Selected: {cvFile.name}</p>}
                    </div>
                </div>
            )}

            {isChoiceStep && currentStep.options && (
                <div className="stack">
                    {currentStep.options.map((option, index) => (
                        <button
                            className={`choice ${selectedIndex === index ? "selected" : ""}`}
                            key={`${currentStep.id}-${index}`}
                            type="button"
                            onClick={() => setSelectedIndex(index)}
                        >
                            {option}
                        </button>
                    ))}
                </div>
            )}

            {state.scenario_generation_status === "fallback" && (
                <p className="muted">Using deterministic adaptive prompts for this step.</p>
            )}

            {error && <p className="error">{error}</p>}

            <button className="button" type="button" onClick={submitStep} disabled={isPending || !canSubmit(currentStep)}>
                {isPending
                    ? currentStep.type === "onboarding" && cvFile ? "Processing CV..." : currentStep.type === "onboarding" ? "Generating..." : "Saving and generating..."
                    : currentStep.type === "onboarding" ? "Start" : "Save and Continue"}
            </button>
        </section>
    );
}
