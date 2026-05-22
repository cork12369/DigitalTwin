import { NextRequest, NextResponse } from "next/server";

import { computeAdminSessionToken } from "@/lib/admin-session";

const ADMIN_AUTH_COOKIE = "dt_admin_session";

export async function middleware(request: NextRequest) {
    const { pathname, search } = request.nextUrl;
    if (!pathname.startsWith("/admin") || pathname.startsWith("/admin/login")) {
        return NextResponse.next();
    }

    const expected = await computeAdminSessionToken();
    const actual = request.cookies.get(ADMIN_AUTH_COOKIE)?.value;
    if (actual && actual === expected) {
        return NextResponse.next();
    }

    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/admin/login";
    const isMutationRoute = /^\/admin\/tokens\/[^/]+\/(analyze|delete|reset|revoke)$/.test(pathname);
    const nextPath = !isMutationRoute && (request.method === "GET" || request.method === "HEAD")
        ? `${pathname}${search}`
        : "/admin/tokens";
    loginUrl.searchParams.set("next", nextPath);
    return NextResponse.redirect(loginUrl);
}

export const config = {
    matcher: ["/admin/:path*"],
};
