import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { adminApiFetch } from "@/lib/api-server";

type Params = {
    params: Promise<{ tokenId: string }>;
};

export async function runTokenMutation(
    request: Request,
    { params }: Params,
    mutation: "activate-v2" | "analyze" | "delete" | "preseed-cards" | "reset" | "revoke",
) {
    const { tokenId } = await params;
    const method = mutation === "delete" ? "DELETE" : "POST";
    const suffix = mutation === "delete" ? "" : `/${mutation}`;
    const redirectPath = safeAdminTokenRedirect(request.headers.get("referer"));

    let response: Response;
    try {
        response = await adminApiFetch(`/api/admin/tokens/${tokenId}${suffix}`, {
            method,
            cache: "no-store",
        });
    } catch (error) {
        console.error(`[token-mutation:${mutation}] Network error:`, error);
        const message = encodeURIComponent("API server unreachable. Make sure the backend is running.");
        redirect(`${redirectPath}${redirectPath.includes("?") ? "&" : "?"}actionError=${message}`);
    }

    if (!response.ok) {
        let detail = await response.text().catch(() => "");
        if (response.status === 401 || response.status === 403) {
            detail = "Admin authentication failed. Check ADMIN_API_SECRET env var.";
        }
        const message = encodeURIComponent(detail || `Unable to ${mutation} token.`);
        redirect(`${redirectPath}${redirectPath.includes("?") ? "&" : "?"}actionError=${message}`);
    }

    revalidatePath("/admin");
    revalidatePath("/admin/tokens");
    revalidatePath(`/admin/tokens/${tokenId}`);
    redirect(redirectPath);
}

export function redirectTokenMutationGet() {
    redirect("/admin/tokens");
}

function safeAdminTokenRedirect(referer: string | null) {
    if (!referer) return "/admin/tokens";
    try {
        const url = new URL(referer);
        if (url.pathname === "/admin/tokens" || url.pathname.startsWith("/admin/tokens/")) {
            return `${url.pathname}${url.search}`;
        }
    } catch {
        return "/admin/tokens";
    }
    return "/admin/tokens";
}
