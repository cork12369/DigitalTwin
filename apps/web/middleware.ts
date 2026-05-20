import { NextRequest, NextResponse } from "next/server";

const ADMIN_AUTH_COOKIE = "dt_admin_session";

export async function middleware(request: NextRequest) {
    const { pathname, search } = request.nextUrl;
    if (!pathname.startsWith("/admin") || pathname.startsWith("/admin/login")) {
        return NextResponse.next();
    }

    const expected = await adminSessionToken();
    const actual = request.cookies.get(ADMIN_AUTH_COOKIE)?.value;
    if (actual && actual === expected) {
        return NextResponse.next();
    }

    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/admin/login";
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
}

export const config = {
    matcher: ["/admin/:path*"],
};

async function adminSessionToken() {
    const password = process.env.ADMIN_PANEL_PASSWORD ?? "change-me-admin-password";
    const secret = process.env.ADMIN_SESSION_SECRET ?? "change-me-admin-session-secret";
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${password}:${secret}`));
    return Array.from(new Uint8Array(digest))
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join("");
}
