import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";

import { adminApiFetch } from "@/lib/api-server";

export async function POST(request: Request) {
    try {
        const payload = await request.json().catch(() => null);
        const label = typeof payload?.label === "string" ? payload.label.trim() : "";

        if (!label) {
            return NextResponse.json({ error: "Participant label is required." }, { status: 400 });
        }

        const response = await adminApiFetch("/api/admin/tokens", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label }),
            cache: "no-store",
        });

        if (!response.ok) {
            const text = await response.text().catch(() => "Unknown error");
            const message = response.status === 401 || response.status === 403
                ? "Admin authentication failed. Check ADMIN_API_SECRET env var."
                : text;
            return NextResponse.json({ error: message }, { status: response.status });
        }

        const data = await response.json();
        revalidatePath("/admin");
        revalidatePath("/admin/tokens");
        return NextResponse.json({
            inviteUrl: data.invite_url,
            token: data.token,
        });
    } catch (error) {
        console.error("[create-token] Error:", error);
        return NextResponse.json(
            { error: "API server unreachable. Make sure the backend is running." },
            { status: 502 },
        );
    }
}
