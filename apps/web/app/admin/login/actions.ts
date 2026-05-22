"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ADMIN_AUTH_COOKIE, adminCookieSecure, adminSessionToken, isAdminPassword } from "@/lib/admin-auth";

export type AdminLoginState = {
    error?: string;
};

export async function loginAdminAction(_prevState: AdminLoginState, formData: FormData): Promise<AdminLoginState> {
    const password = String(formData.get("password") ?? "");
    const next = safeNextPath(String(formData.get("next") ?? "/admin"));

    if (!isAdminPassword(password)) {
        return { error: "Incorrect admin password." };
    }

    const cookieStore = await cookies();
    cookieStore.set(ADMIN_AUTH_COOKIE, await adminSessionToken(), {
        httpOnly: true,
        sameSite: "lax",
        secure: adminCookieSecure(),
        path: "/",
        maxAge: 60 * 60 * 8,
    });

    redirect(next);
}

function safeNextPath(value: string) {
    if (!value.startsWith("/admin") || value.startsWith("/admin/login")) {
        return "/admin";
    }
    if (/^\/admin\/tokens\/[^/]+\/(analyze|delete|reset|revoke)$/.test(value)) {
        return "/admin/tokens";
    }
    return value;
}
