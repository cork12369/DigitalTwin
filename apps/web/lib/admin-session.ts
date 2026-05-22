/**
 * Shared admin session token computation.
 * Uses Web Crypto API which is available in both Edge Runtime (middleware)
 * and Node.js runtime (server actions / route handlers).
 */

const ADMIN_PASSWORD_ENV = "ADMIN_PANEL_PASSWORD";
const ADMIN_SESSION_SECRET_ENV = "ADMIN_SESSION_SECRET";
const DEFAULT_PASSWORD = "change-me-admin-password";
const DEFAULT_SECRET = "change-me-admin-session-secret";

export async function computeAdminSessionToken(): Promise<string> {
    const password = process.env[ADMIN_PASSWORD_ENV] ?? DEFAULT_PASSWORD;
    const secret = process.env[ADMIN_SESSION_SECRET_ENV] ?? DEFAULT_SECRET;
    const input = `${password}:${secret}`;
    const data = new TextEncoder().encode(input);
    const hashBuffer = await crypto.subtle.digest("SHA-256", data);
    return Array.from(new Uint8Array(hashBuffer))
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join("");
}