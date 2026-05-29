"use client";

import Link from "next/link";
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
    replay_scenario_id?: string | null;
    replay_index?: number | null;
    source_context_step_id?: string | null;
    context_kind?: string | null;
    holdout_slot?: boolean | null;
    holdout_partition?: string | null;
    phase?: string | null;
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
    replay_context_count: number;
    replay_scenario_count: number;
    max_replay_scenarios: number;
    twin_responses_per_replay: number;
    scenario_generation_status?: string | null;
    scenario_generation_message?: string | null;
};

export function ScenarioClient({ token, initialState }: { token: string; initialState: SessionState }) {
    const [state, setState] = useState(initialState);
    const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
    const [answerMode, setAnswerMode] = useState<"binary" | "custom_text" | "indifferent">("binary");
    const [text, setText] = useState("");
    const [ranked, setRanked] = useState<string[]>([]);
    const [rejected, setRejected] = useState<string[]>([]);
    const [correctionText, setCorrectionText] = useState("");
    const [cvFile, setCvFile] = useState<File | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [isPending, startTransition] = useTransition();

    const currentStep = useMemo(
        () => state.steps.find((step) => step.id === state.current_step) ?? null,
        [state.current_step, state.steps],
    );

    const maxReplayScenarios = state.max_replay_scenarios ?? 2;
    const progressMax = state.max_adaptive_questions + maxReplayScenarios;
    const progressValue = Math.min(state.adaptive_question_count, state.max_adaptive_questions) + Math.min(state.replay_scenario_count ?? 0, maxReplayScenarios);
    const progressPercent = Math.round((progressValue / progressMax) * 100);
    const isChoiceStep = currentStep?.type === "triad" || currentStep?.type === "duel";

    function resetInputs() {
        setSelectedIndex(null);
        setAnswerMode("binary");
        setText("");
        setRanked([]);
        setRejected([]);
        setCorrectionText("");
        setCvFile(null);
    }

    async function refreshState(sessionId = state.session_id) {
        const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}/state`, { cache: "no-store" });
        if (!response.ok) throw new Error(await response.text());
        setState(await response.json());
    }

    function buildAnswer(step: ScenarioStep) {
        if (step.type === "onboarding") return { user_profile: text.trim() };
        if ((step.type === "triad" || step.type === "duel") && answerMode === "indifferent") {
            return { mode: "indifferent", text: text.trim() };
        }
        if ((step.type === "triad" || step.type === "duel") && answerMode === "custom_text") {
            return { mode: "custom_text", text: text.trim() };
        }
        if ((step.type === "triad" || step.type === "duel") && selectedIndex !== null) {
            return {
                selected_index: selectedIndex,
                selected_option: step.options?.[selectedIndex] ?? "",
            };
        }
        if (step.type === "context_flip") return { text: text.trim() };
        if (step.type === "correction") return { text: text.trim() };
        if (step.type === "twin_rank") {
            return {
                ranked_options: ranked,
                rejected_options: rejected,
                correction_text: correctionText.trim(),
            };
        }
        return {};
    }

    function canSubmit(step: ScenarioStep) {
        if (step.type === "onboarding") return Boolean(cvFile) || text.trim().length >= 2;
        if (step.type === "triad" || step.type === "duel") {
            if (answerMode === "indifferent") return true;
            if (answerMode === "custom_text") return text.trim().length >= 1;
            return selectedIndex !== null;
        }
        if (step.type === "context_flip") return text.trim().length >= 1;
        if (step.type === "correction") return text.trim().length >= 1;
        if (step.type === "twin_rank") return ranked.length === (step.options?.length ?? 0);
        return true;
    }

    function toggleRank(option: string) {
        setRanked((current) => current.includes(option) ? current.filter((item) => item !== option) : [...current, option]);
    }

    function toggleRejected(option: string) {
        setRejected((current) => current.includes(option) ? current.filter((item) => item !== option) : [...current, option]);
    }

    function stepLabel(step: ScenarioStep) {
        if (step.holdout_slot) return "Holdout check";
        if (step.type === "onboarding") return "Profile setup";
        if (step.type === "correction") return "Correction";
        if (step.type === "context_flip") return `Replay ${step.replay_index ?? (state.replay_context_count + 1)} of ${maxReplayScenarios}`;
        if (step.type === "twin_rank") return `Replay ${step.replay_index ?? (state.replay_scenario_count + 1)} response ranking`;
        return `MCQ ${state.adaptive_question_count + 1} of up to ${state.max_adaptive_questions}`;
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
                            answer_mode: currentStep.type === "triad" || currentStep.type === "duel" ? answerMode : undefined,
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
                <Link className="button" href={`/train/${encodeURIComponent(token)}`}>Continue to Initialization Chat</Link>
            </section>
        );
    }

    if (!currentStep) {
        return <section className="panel error">Unable to find current step: {state.current_step}</section>;
    }

    return (
        <section className="panel stack">
            <div className="row">
                <span className="eyebrow">{stepLabel(currentStep)}</span>
                <span className="status">
                    <span className="dot" />
                    MCQ {state.adaptive_question_count}/{state.max_adaptive_questions} | Replay {state.replay_scenario_count}/{maxReplayScenarios} | {progressPercent}%
                </span>
            </div>
            <progress value={progressValue} max={progressMax} />
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
                        <strong>Upload a CV instead</strong>
                        <input
                            accept=".pdf,application/pdf,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.md,text/markdown,text/plain"
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
                            onClick={() => {
                                setAnswerMode("binary");
                                setSelectedIndex(index);
                            }}
                        >
                            {option}
                        </button>
                    ))}
                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        <button
                            className={`button secondary ${answerMode === "indifferent" ? "selected" : ""}`}
                            type="button"
                            onClick={() => {
                                setAnswerMode("indifferent");
                                setSelectedIndex(null);
                            }}
                        >
                            No preference
                        </button>
                        <button
                            className={`button secondary ${answerMode === "custom_text" ? "selected" : ""}`}
                            type="button"
                            onClick={() => {
                                setAnswerMode("custom_text");
                                setSelectedIndex(null);
                            }}
                        >
                            Custom answer
                        </button>
                    </div>
                    {answerMode !== "binary" && (
                        <textarea
                            value={text}
                            onChange={(event) => setText(event.target.value)}
                            placeholder={answerMode === "indifferent" ? "Optional: what makes these options feel equivalent?" : "Describe your actual choice boundary..."}
                        />
                    )}
                </div>
            )}

            {(currentStep.type === "context_flip" || currentStep.type === "correction") && (
                <textarea
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    placeholder={currentStep.type === "correction" ? "Correct the model's current read..." : "Write what changes, what stays the same, and what would decide it..."}
                />
            )}

            {currentStep.type === "twin_rank" && currentStep.options && (
                <div className="stack">
                    {currentStep.options.map((option) => (
                        <div className="rank-option" key={option}>
                            <button
                                className={`choice ${ranked.includes(option) ? "selected" : ""}`}
                                type="button"
                                onClick={() => toggleRank(option)}
                            >
                                {ranked.includes(option) ? `${ranked.indexOf(option) + 1}. ` : ""}{option}
                            </button>
                            <button
                                className={`button secondary reject-button ${rejected.includes(option) ? "selected" : ""}`}
                                type="button"
                                onClick={() => toggleRejected(option)}
                            >
                                {rejected.includes(option) ? "Rejected" : "Reject"}
                            </button>
                        </div>
                    ))}
                    <textarea
                        value={correctionText}
                        onChange={(event) => setCorrectionText(event.target.value)}
                        placeholder="Optional correction: what did these responses miss?"
                    />
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
