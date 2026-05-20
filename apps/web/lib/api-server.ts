import "server-only";

export const API_SERVER_BASE_URL =
    process.env.API_INTERNAL_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://127.0.0.1:8000";

export function adminApiHeaders(extraHeaders?: HeadersInit): HeadersInit {
    const headers = new Headers(extraHeaders);
    headers.set("X-Admin-Secret", process.env.ADMIN_API_SECRET ?? "change-me-admin-api-secret");
    return headers;
}

export async function adminApiFetch(path: string, init?: RequestInit): Promise<Response> {
    return fetch(`${API_SERVER_BASE_URL}${path}`, {
        ...init,
        headers: adminApiHeaders(init?.headers),
        cache: init?.cache ?? "no-store",
    });
}
