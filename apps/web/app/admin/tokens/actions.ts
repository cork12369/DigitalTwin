"use server";

import { revalidatePath } from "next/cache";

import { adminApiFetch } from "@/lib/api-server";

export type CreateTokenState = {
    inviteUrl?: string;
    token?: string;
    error?: string;
};

export async function createTokenAction(_prevState: CreateTokenState, formData: FormData): Promise<CreateTokenState> {
    const label = String(formData.get("label") ?? "").trim();

    if (!label) {
        return { error: "Participant label is required." };
    }

    try {
        const response = await adminApiFetch("/api/admin/tokens", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label }),
            cache: "no-store",
        });

        if (!response.ok) {
            return { error: await response.text() };
        }

        const data = await response.json();
        revalidatePath("/admin/tokens");
        return { inviteUrl: data.invite_url, token: data.token };
    } catch (error) {
        return { error: error instanceof Error ? error.message : "Unable to create token." };
    }
}

export async function revokeTokenAction(formData: FormData) {
    const tokenId = String(formData.get("tokenId") ?? "");
    if (!tokenId) return;

    await adminApiFetch(`/api/admin/tokens/${tokenId}/revoke`, {
        method: "POST",
        cache: "no-store",
    });
    revalidatePath("/admin/tokens");
}

export async function deleteRevokedTokenAction(formData: FormData) {
    const tokenId = String(formData.get("tokenId") ?? "");
    if (!tokenId) return;

    await adminApiFetch(`/api/admin/tokens/${tokenId}`, {
        method: "DELETE",
        cache: "no-store",
    });
    revalidatePath("/admin");
    revalidatePath("/admin/tokens");
}

export async function resetTokenAction(formData: FormData) {
    const tokenId = String(formData.get("tokenId") ?? "");
    if (!tokenId) return;

    await adminApiFetch(`/api/admin/tokens/${tokenId}/reset`, {
        method: "POST",
        cache: "no-store",
    });
    revalidatePath("/admin/tokens");
}

export async function analyzeTokenAction(formData: FormData) {
    const tokenId = String(formData.get("tokenId") ?? "");
    if (!tokenId) return;

    await adminApiFetch(`/api/admin/tokens/${tokenId}/analyze`, {
        method: "POST",
        cache: "no-store",
    });
    revalidatePath("/admin");
    revalidatePath("/admin/tokens");
    revalidatePath(`/admin/tokens/${tokenId}`);
}
