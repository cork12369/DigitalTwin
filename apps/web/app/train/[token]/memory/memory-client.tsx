"use client";

import { useMemo, useState, useTransition } from "react";

import { API_BASE_URL, type MemoryCard, type MemoryCardsState } from "@/lib/api";

const BUCKETS = [
    { key: "draft", label: "Draft", status: "draft", priority: "medium" },
    { key: "core", label: "Core", status: "reviewed", priority: "core" },
    { key: "high", label: "High", status: "reviewed", priority: "high" },
    { key: "medium", label: "Medium", status: "reviewed", priority: "medium" },
    { key: "low", label: "Low", status: "reviewed", priority: "low" },
];

function bucketFor(card: MemoryCard) {
    return card.status === "draft" ? "draft" : card.priority;
}

export function MemoryClient({ token, initialState }: { token: string; initialState: MemoryCardsState }) {
    const [state, setState] = useState(initialState);
    const [draggedCardId, setDraggedCardId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [isPending, startTransition] = useTransition();

    const cardsByBucket = useMemo(() => {
        const grouped = new Map<string, MemoryCard[]>();
        for (const bucket of BUCKETS) grouped.set(bucket.key, []);
        for (const card of state.cards) grouped.get(bucketFor(card))?.push(card);
        return grouped;
    }, [state.cards]);

    async function updateCard(cardId: string, patch: Partial<MemoryCard> & { pillar_keys?: string[] }) {
        const response = await fetch(`${API_BASE_URL}/api/training/cards/${cardId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token, ...patch }),
            cache: "no-store",
        });
        if (!response.ok) throw new Error(await response.text());
        setState(await response.json());
    }

    function dropIntoBucket(bucket: (typeof BUCKETS)[number]) {
        if (!draggedCardId) return;
        setError(null);
        startTransition(async () => {
            try {
                await updateCard(draggedCardId, { status: bucket.status, priority: bucket.priority });
            } catch (dropError) {
                setError(dropError instanceof Error ? dropError.message : "Unable to move card.");
            } finally {
                setDraggedCardId(null);
            }
        });
    }

    async function deleteCard(cardId: string) {
        const response = await fetch(`${API_BASE_URL}/api/training/cards/${cardId}/delete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
            cache: "no-store",
        });
        if (!response.ok) throw new Error(await response.text());
        setState(await response.json());
    }

    return (
        <section className="stack">
            <section className="panel stack">
                <div className="row">
                    <div>
                        <span className="eyebrow">Twin Readiness</span>
                        <h2>{state.readiness.overall_percent}%</h2>
                    </div>
                    <span className="status"><span className="dot" />{state.readiness.reviewed_card_count} reviewed</span>
                </div>
                <progress value={state.readiness.overall_percent} max={100} />
                <div className="grid">
                    {state.readiness.pillars.map((pillar) => (
                        <div className="pillar-meter" key={pillar.key}>
                            <div className="row">
                                <strong>{pillar.label}</strong>
                                <span className="muted">{pillar.score}/{pillar.target}</span>
                            </div>
                            <progress value={pillar.percent} max={100} />
                        </div>
                    ))}
                </div>
            </section>

            {error && <p className="error">{error}</p>}

            <section className="memory-board">
                {BUCKETS.map((bucket) => (
                    <div
                        className="memory-column panel"
                        key={bucket.key}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => dropIntoBucket(bucket)}
                    >
                        <div className="row">
                            <h2>{bucket.label}</h2>
                            <span className="muted">{cardsByBucket.get(bucket.key)?.length ?? 0}</span>
                        </div>
                        <div className="stack">
                            {(cardsByBucket.get(bucket.key) ?? []).map((card) => (
                                <MemoryCardEditor
                                    card={card}
                                    disabled={isPending}
                                    key={card.id}
                                    onDelete={deleteCard}
                                    onDragStart={() => setDraggedCardId(card.id)}
                                    onSave={updateCard}
                                    pillars={state.pillars}
                                />
                            ))}
                        </div>
                    </div>
                ))}
            </section>
        </section>
    );
}

function MemoryCardEditor({
    card,
    disabled,
    onDelete,
    onDragStart,
    onSave,
    pillars,
}: {
    card: MemoryCard;
    disabled: boolean;
    onDelete: (cardId: string) => Promise<void>;
    onDragStart: () => void;
    onSave: (cardId: string, patch: Partial<MemoryCard> & { pillar_keys?: string[] }) => Promise<void>;
    pillars: Array<{ key: string; label: string; description: string }>;
}) {
    const [title, setTitle] = useState(card.title);
    const [body, setBody] = useState(card.body);
    const [priority, setPriority] = useState(card.priority);
    const [status, setStatus] = useState(card.status);
    const [pillarKeys, setPillarKeys] = useState(card.pillar_links.map((link) => link.pillar_key));
    const [error, setError] = useState<string | null>(null);
    const [isPending, startTransition] = useTransition();

    function togglePillar(key: string) {
        setPillarKeys((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key]);
    }

    function save() {
        setError(null);
        startTransition(async () => {
            try {
                await onSave(card.id, { title, body, priority, status, pillar_keys: pillarKeys });
            } catch (saveError) {
                setError(saveError instanceof Error ? saveError.message : "Unable to save card.");
            }
        });
    }

    function remove() {
        if (!window.confirm("Delete this memory card? The source chat transcript will remain.")) return;
        setError(null);
        startTransition(async () => {
            try {
                await onDelete(card.id);
            } catch (deleteError) {
                setError(deleteError instanceof Error ? deleteError.message : "Unable to delete card.");
            }
        });
    }

    return (
        <article className="memory-card" draggable onDragStart={onDragStart}>
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
            <textarea value={body} onChange={(event) => setBody(event.target.value)} />
            {card.source_quote && <blockquote>{card.source_quote}</blockquote>}
            {card.duplicate_suggestions.length > 0 && (
                <div className="context-panel">
                    <strong>Possible duplicate</strong>
                    {card.duplicate_suggestions.map((suggestion) => (
                        <p className="muted" key={suggestion.id}>
                            {suggestion.matched_card_title ?? suggestion.matched_card_id} · {suggestion.confidence}
                        </p>
                    ))}
                </div>
            )}
            <div className="row">
                <label className="stack card-select">
                    <span className="field-label">Status</span>
                    <select value={status} onChange={(event) => setStatus(event.target.value)}>
                        <option value="draft">Draft</option>
                        <option value="reviewed">Reviewed</option>
                    </select>
                </label>
                <label className="stack card-select">
                    <span className="field-label">Priority</span>
                    <select value={priority} onChange={(event) => setPriority(event.target.value)}>
                        <option value="core">Core</option>
                        <option value="high">High</option>
                        <option value="medium">Medium</option>
                        <option value="low">Low</option>
                    </select>
                </label>
            </div>
            <div className="pillar-checks">
                {pillars.map((pillar) => (
                    <label key={pillar.key}>
                        <input checked={pillarKeys.includes(pillar.key)} onChange={() => togglePillar(pillar.key)} type="checkbox" />
                        {pillar.label}
                    </label>
                ))}
            </div>
            {error && <p className="error">{error}</p>}
            <div className="row">
                <button className="button" type="button" onClick={save} disabled={disabled || isPending || pillarKeys.length === 0}>
                    Save
                </button>
                <button className="button danger" type="button" onClick={remove} disabled={disabled || isPending}>
                    Delete
                </button>
            </div>
        </article>
    );
}
