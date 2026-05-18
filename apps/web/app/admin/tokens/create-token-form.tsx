"use client";

import { useActionState } from "react";

import { createTokenAction, type CreateTokenState } from "./actions";

const initialState: CreateTokenState = {};

export function CreateTokenForm() {
    const [state, formAction, pending] = useActionState(createTokenAction, initialState);

    return (
        <form className="stack" action={formAction}>
            <label className="stack">
                <span className="muted">Participant label</span>
                <input name="label" placeholder="e.g. Participant A / user email / study cohort" />
            </label>
            <button className="button" type="submit" disabled={pending}>
                {pending ? "Generating..." : "Generate Personal Token"}
            </button>

            {state.error && <p className="error">{state.error}</p>}
            {state.inviteUrl && (
                <div className="panel stack compact-panel">
                    <strong>Invite link generated</strong>
                    <code>{state.inviteUrl}</code>
                    <button className="button secondary" type="button" onClick={() => navigator.clipboard.writeText(state.inviteUrl ?? "")}>
                        Copy Invite Link
                    </button>
                </div>
            )}
        </form>
    );
}