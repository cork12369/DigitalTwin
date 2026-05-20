"use client";

import { useActionState } from "react";

import { loginAdminAction, type AdminLoginState } from "./actions";

const initialState: AdminLoginState = {};

export function AdminLoginForm({ next }: { next: string }) {
    const [state, formAction, pending] = useActionState(loginAdminAction, initialState);

    return (
        <form className="stack" action={formAction}>
            <input type="hidden" name="next" value={next} />
            <label className="stack">
                <span className="muted">Admin password</span>
                <input name="password" type="password" placeholder="Enter admin secret" autoComplete="current-password" />
            </label>
            {state.error && <p className="error">{state.error}</p>}
            <button className="button" type="submit" disabled={pending}>
                {pending ? "Unlocking..." : "Unlock Admin Panel"}
            </button>
        </form>
    );
}
