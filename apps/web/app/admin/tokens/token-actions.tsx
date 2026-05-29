"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function TokenActions({ tokenId, status }: { tokenId: string; status: string }) {
    const isRevoked = status === "revoked";
    const encodedTokenId = encodeURIComponent(tokenId);
    const router = useRouter();
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    async function handleAction(action: "activate-v2" | "analyze" | "delete" | "preseed-cards" | "reset" | "revoke") {
        setBusy(action);
        setError(null);
        try {
            const response = await fetch(`/admin/tokens/${encodedTokenId}/${action}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });

            if (response.status === 401 || response.status === 403) {
                setError("Session expired. Redirecting to login...");
                window.location.href = `/admin/login?next=/admin/tokens`;
                return;
            }

            if (!response.ok) {
                const text = await response.text().catch(() => "Unknown error");
                setError(text || `Failed to ${action} token.`);
                return;
            }

            router.refresh();
        } catch {
            setError("Network error. Please try again.");
        } finally {
            setBusy(null);
        }
    }

    return (
        <div className="row" style={{ justifyContent: "flex-end" }}>
            <button
                className="button secondary"
                disabled={isRevoked || busy !== null}
                onClick={() => handleAction("preseed-cards")}
                type="button"
            >
                {busy === "preseed-cards" ? "Seeding..." : "Preseed Cards"}
            </button>
            <button
                className="button secondary"
                disabled={isRevoked || busy !== null}
                onClick={() => handleAction("activate-v2")}
                type="button"
            >
                {busy === "activate-v2" ? "Activating..." : "Activate V2"}
            </button>
            <button
                className="button secondary"
                disabled={isRevoked || busy !== null}
                onClick={() => handleAction("analyze")}
                type="button"
            >
                {busy === "analyze" ? "Analyzing..." : "Analyze"}
            </button>
            <button
                className="button secondary"
                disabled={busy !== null}
                onClick={() => handleAction("reset")}
                type="button"
            >
                {busy === "reset" ? "Resetting..." : "Reset"}
            </button>
            <button
                className="button danger"
                disabled={isRevoked || busy !== null}
                onClick={() => handleAction("revoke")}
                type="button"
            >
                {busy === "revoke" ? "Revoking..." : "Revoke"}
            </button>
            {isRevoked && (
                <button
                    className="button danger"
                    disabled={busy !== null}
                    onClick={() => handleAction("delete")}
                    type="button"
                >
                    {busy === "delete" ? "Deleting..." : "Delete"}
                </button>
            )}
            {error && <span className="error" style={{ marginLeft: 8 }}>{error}</span>}
        </div>
    );
}
