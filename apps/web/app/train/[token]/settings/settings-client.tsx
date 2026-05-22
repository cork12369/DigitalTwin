"use client";

import { useState, useTransition } from "react";

import { API_BASE_URL, type TrainingState } from "@/lib/api";

export function GuideSettingsClient({ token, initialState }: { token: string; initialState: TrainingState }) {
    const [customPrompt, setCustomPrompt] = useState(initialState.guide_custom_prompt ?? "");
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isPending, startTransition] = useTransition();

    function save() {
        setSaved(false);
        setError(null);
        startTransition(async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/api/training/settings`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token, custom_prompt: customPrompt }),
                    cache: "no-store",
                });
                if (!response.ok) throw new Error(await response.text());
                await response.json();
                setSaved(true);
            } catch (saveError) {
                setError(saveError instanceof Error ? saveError.message : "Unable to save guide settings.");
            }
        });
    }

    return (
        <section className="panel stack">
            <label className="stack">
                <span className="field-label">Style and topic preferences</span>
                <textarea
                    value={customPrompt}
                    onChange={(event) => setCustomPrompt(event.target.value)}
                    placeholder="Example: keep the tone direct and analytical; ask more about creative trade-offs and fewer workplace examples."
                />
            </label>
            <div className="context-panel">
                <strong>Boundary</strong>
                <p className="muted">These notes guide tone and topic selection only. The backend still controls safety, coverage, and memory extraction.</p>
            </div>
            {saved && <p className="status"><span className="dot" />Saved</p>}
            {error && <p className="error">{error}</p>}
            <button className="button" type="button" onClick={save} disabled={isPending}>
                {isPending ? "Saving..." : "Save Settings"}
            </button>
        </section>
    );
}
