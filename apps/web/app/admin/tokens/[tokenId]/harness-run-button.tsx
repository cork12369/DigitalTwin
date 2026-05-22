"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function HarnessRunButton({ tokenId }: { tokenId: string }) {
    const router = useRouter();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function runHarness() {
        setBusy(true);
        setError(null);
        try {
            const response = await fetch(`/admin/tokens/${encodeURIComponent(tokenId)}/harness/run`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
            if (response.status === 401 || response.status === 403) {
                setError("Admin session expired. Redirecting to login...");
                window.location.href = `/admin/login?next=/admin/tokens/${encodeURIComponent(tokenId)}`;
                return;
            }
            if (!response.ok) {
                const text = await response.text().catch(() => "");
                setError(text || "Unable to run diagnostics harness.");
                return;
            }
            router.refresh();
        } catch {
            setError("Network error. Make sure the backend is running.");
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="stack" style={{ alignItems: "flex-start", gap: 8 }}>
            <button className="button" disabled={busy} onClick={runHarness} type="button">
                {busy ? "Running Harness..." : "Run Harness"}
            </button>
            {error && <span className="error">{error}</span>}
        </div>
    );
}
