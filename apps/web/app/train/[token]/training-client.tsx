"use client";

import Link from "next/link";
import { useMemo, useState, useTransition } from "react";

import { API_BASE_URL, type TrainingState } from "@/lib/api";

export function TrainingClient({ token, initialState }: { token: string; initialState: TrainingState }) {
    const [state, setState] = useState(initialState);
    const [content, setContent] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(initialState.compaction_notice ?? null);
    const [isPending, startTransition] = useTransition();

    const pairProgress = state.pair_count % state.pair_block_size;
    const readinessPercent = Math.max(0, Math.min(100, state.readiness.overall_percent ?? 0));
    const sortedMessages = useMemo(
        () => [...state.messages].sort((left, right) => left.message_index - right.message_index),
        [state.messages],
    );

    async function refreshState() {
        const response = await fetch(`${API_BASE_URL}/api/training/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
            cache: "no-store",
        });
        if (!response.ok) throw new Error(await response.text());
        const nextState = await response.json();
        setState(nextState);
        if (nextState.draft_card_count > state.draft_card_count) {
            setNotice("New draft memory cards are ready.");
        }
    }

    function sendMessage() {
        const trimmed = content.trim();
        if (!trimmed) return;
        setError(null);
        startTransition(async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/api/training/${state.chat_session_id}/messages`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token, content: trimmed }),
                    cache: "no-store",
                });
                if (!response.ok) throw new Error(await response.text());
                const nextState = await response.json();
                setState(nextState);
                setContent("");
                if (nextState.compaction_notice) setNotice(nextState.compaction_notice);
            } catch (sendError) {
                setError(sendError instanceof Error ? sendError.message : "Unable to send message.");
            }
        });
    }

    return (
        <section className="train-shell">
            <aside className="panel stack train-sidebar">
                <div>
                    <span className="eyebrow">Twin Readiness</span>
                    <h2>{readinessPercent}%</h2>
                    <progress value={readinessPercent} max={100} />
                </div>
                <div className="stack pillar-list">
                    {state.readiness.pillars.map((pillar) => (
                        <div className="pillar-meter" key={pillar.key}>
                            <div className="row">
                                <strong>{pillar.label}</strong>
                                <span className="muted">{pillar.percent}%</span>
                            </div>
                            <progress value={pillar.percent} max={100} />
                        </div>
                    ))}
                </div>
                <div className="compact-panel">
                    <div className="row">
                        <strong>Compaction</strong>
                        <span className="muted">{pairProgress}/{state.pair_block_size}</span>
                    </div>
                    <progress value={pairProgress} max={state.pair_block_size} />
                    {state.latest_compaction_status && <p className="muted">Latest: {state.latest_compaction_status}</p>}
                </div>
                <div className="row" style={{ justifyContent: "flex-start" }}>
                    <Link className="button secondary" href={`/train/${encodeURIComponent(token)}/memory`}>Cards</Link>
                    <Link className="button secondary" href={`/train/${encodeURIComponent(token)}/settings`}>Settings</Link>
                    <button className="button secondary" type="button" onClick={() => void refreshState()} disabled={isPending}>Refresh</button>
                </div>
            </aside>

            <section className="panel stack chat-panel">
                <div className="chat-log">
                    {sortedMessages.map((message) => (
                        <article className={`chat-message ${message.role}`} key={message.id}>
                            <span className="eyebrow">{message.role === "user" ? "You" : "Guide"}</span>
                            <p>{message.content}</p>
                        </article>
                    ))}
                </div>

                {notice && (
                    <div className="toast row">
                        <span>{notice}</span>
                        <Link className="button secondary" href={`/train/${encodeURIComponent(token)}/memory`}>Review</Link>
                        <button className="button secondary" type="button" onClick={() => setNotice(null)}>Dismiss</button>
                    </div>
                )}

                {error && <p className="error">{error}</p>}

                <div className="chat-composer">
                    <textarea
                        value={content}
                        onChange={(event) => setContent(event.target.value)}
                        placeholder="Reply with a real decision, a messy trade-off, or a situation you want to unpack..."
                    />
                    <button className="button" type="button" onClick={sendMessage} disabled={isPending || content.trim().length === 0}>
                        {isPending ? "Thinking..." : "Send"}
                    </button>
                </div>
            </section>
        </section>
    );
}
