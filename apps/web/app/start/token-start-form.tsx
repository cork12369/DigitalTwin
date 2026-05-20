"use client";

import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";

export function TokenStartForm() {
    const router = useRouter();
    const [token, setToken] = useState("");
    const [error, setError] = useState("");

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const normalizedToken = token.trim();

        if (!normalizedToken) {
            setError("Enter the token from your invite.");
            return;
        }

        router.push(`/play/${encodeURIComponent(normalizedToken)}`);
    }

    return (
        <form className="panel stack start-form" onSubmit={handleSubmit}>
            <label className="stack">
                <span className="field-label">Auth token</span>
                <input
                    autoComplete="off"
                    name="token"
                    onChange={(event) => {
                        setToken(event.target.value);
                        setError("");
                    }}
                    placeholder="Paste your generated token"
                    value={token}
                />
            </label>
            {error && <p className="error">{error}</p>}
            <button className="button" type="submit">Start Questionnaire</button>
        </form>
    );
}
