"use client";

import { useState } from "react";

export function AuthKeyReveal({ authKey, inviteUrl }: { authKey?: string | null; inviteUrl?: string | null }) {
    const [revealed, setRevealed] = useState(false);

    if (!authKey) {
        return (
            <div className="context-panel stack">
                <strong>Key Management</strong>
                <p className="muted">No recoverable auth key is stored for this token. Older tokens were hash-only.</p>
            </div>
        );
    }

    const displayKey = revealed ? authKey : `${authKey.slice(0, 8)}...${authKey.slice(-6)}`;

    return (
        <div className="context-panel stack">
            <strong>Key Management</strong>
            <div className="stack">
                <span className="muted">Participant auth key</span>
                <code>{displayKey}</code>
            </div>
            {revealed && inviteUrl && (
                <div className="stack">
                    <span className="muted">Invite link</span>
                    <code>{inviteUrl}</code>
                </div>
            )}
            <div className="row" style={{ justifyContent: "flex-start" }}>
                <button className="button secondary" type="button" onClick={() => setRevealed((current) => !current)}>
                    {revealed ? "Hide Key" : "Reveal Key"}
                </button>
                <button className="button secondary" type="button" onClick={() => navigator.clipboard.writeText(authKey)}>
                    Copy Key
                </button>
                {inviteUrl && (
                    <button className="button secondary" type="button" onClick={() => navigator.clipboard.writeText(inviteUrl)}>
                        Copy Invite Link
                    </button>
                )}
            </div>
        </div>
    );
}
