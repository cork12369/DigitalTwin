import { revalidatePath } from "next/cache";

import { adminApiFetch } from "@/lib/api-server";

type RouteContext = {
    params: Promise<{ tokenId: string }>;
};

export async function POST(_request: Request, { params }: RouteContext) {
    const { tokenId } = await params;
    let response: Response;
    try {
        response = await adminApiFetch(`/api/admin/tokens/${tokenId}/harness/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            cache: "no-store",
        });
    } catch {
        return new Response("API server unreachable. Make sure the backend is running.", { status: 502 });
    }

    const text = await response.text();
    if (!response.ok) {
        return new Response(text || "Unable to run diagnostics harness.", { status: response.status });
    }

    revalidatePath("/admin");
    revalidatePath("/admin/tokens");
    revalidatePath(`/admin/tokens/${tokenId}`);
    return new Response(text, {
        status: 200,
        headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
}
