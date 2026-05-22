"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState, useTransition } from "react";

type CreateTokenState = {
    inviteUrl?: string;
    token?: string;
    error?: string;
};

export function CreateTokenForm() {
    const router = useRouter();
    const [label, setLabel] = useState("");
    const [state, setState] = useState<CreateTokenState>({});
    const [pending, startTransition] = useTransition();

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const trimmedLabel = label.trim();
        if (!trimmedLabel) {
            setState({ error: "Participant label is required." });
            return;
        }

        startTransition(async () => {
            try {
                const response = await fetch("/admin/tokens/create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ label: trimmedLabel }),
                    cache: "no-store",
                });
                const contentType = response.headers.get("content-type") ?? "";
                if (!contentType.includes("application/json")) {
                    if (response.status === 401 || response.status === 403) {
                        setState({ error: "Admin session expired. Log in again, then retry." });
                    } else {
                        setState({ error: "Server error. The API server may be down or misconfigured." });
                    }
                    return;
                }
                const data = await response.json();
                if (!response.ok) {
                    setState({ error: data.error ?? "Unable to create token." });
                    return;
                }
                setState({ inviteUrl: data.inviteUrl, token: data.token });
                setLabel("");
                router.refresh();
            } catch (error) {
                setState({ error: error instanceof Error ? error.message : "Unable to create token." });
            }
        });
    }

    return (
        <form className="stack" onSubmit={handleSubmit}>
            <label className="stack">
                <span className="muted">Participant label</span>
                <input
                    name="label"
                    onChange={(event) => {
                        setLabel(event.target.value);
                        if (state.error) setState({});
                    }}
                    placeholder="e.g. Participant A / user email / study cohort"
                    value={label}
                />
            </label>
            <button className="button" type="submit" disabled={pending}>
                {pending ? "Generating..." : "Generate Personal Token"}
            </button>

            {state.error && <p className="error">{state.error}</p>}
            {state.inviteUrl && (
                <div className="panel stack compact-panel">
                    <strong>Invite link generated</strong>
                    {state.token && (
                        <>
                            <span className="muted">Auth token</span>
                            <code>{state.token}</code>
                        </>
                    )}
                    <span className="muted">Direct questionnaire link</span>
                    <code>{state.inviteUrl}</code>
                    <button className="button secondary" type="button" onClick={() => navigator.clipboard.writeText(state.inviteUrl ?? "")}>
                        Copy Invite Link
                    </button>
                </div>
            )}
        </form>
    );
}
