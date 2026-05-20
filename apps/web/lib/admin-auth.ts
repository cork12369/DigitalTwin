import "server-only";

import crypto from "crypto";

export const ADMIN_AUTH_COOKIE = "dt_admin_session";

export function adminSessionToken() {
    return crypto
        .createHash("sha256")
        .update(`${adminPassword()}:${adminSessionSecret()}`)
        .digest("hex");
}

export function isAdminPassword(value: string) {
    const expected = adminPassword();
    const valueBuffer = Buffer.from(value);
    const expectedBuffer = Buffer.from(expected);
    return valueBuffer.length === expectedBuffer.length && crypto.timingSafeEqual(valueBuffer, expectedBuffer);
}

function adminPassword() {
    return process.env.ADMIN_PANEL_PASSWORD ?? "change-me-admin-password";
}

function adminSessionSecret() {
    return process.env.ADMIN_SESSION_SECRET ?? "change-me-admin-session-secret";
}
