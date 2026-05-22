import "server-only";

import crypto from "crypto";

import { computeAdminSessionToken } from "@/lib/admin-session";

export const ADMIN_AUTH_COOKIE = "dt_admin_session";

export { computeAdminSessionToken as adminSessionToken };

export function isAdminPassword(value: string) {
    const expected = adminPassword();
    const valueBuffer = Buffer.from(value);
    const expectedBuffer = Buffer.from(expected);
    return valueBuffer.length === expectedBuffer.length && crypto.timingSafeEqual(valueBuffer, expectedBuffer);
}

export function adminCookieSecure() {
    return process.env.ADMIN_COOKIE_SECURE === "true";
}

function adminPassword() {
    return process.env.ADMIN_PANEL_PASSWORD ?? "change-me-admin-password";
}

function adminSessionSecret() {
    return process.env.ADMIN_SESSION_SECRET ?? "change-me-admin-session-secret";
}
