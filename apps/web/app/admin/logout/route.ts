import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ADMIN_AUTH_COOKIE } from "@/lib/admin-auth";

export async function GET() {
    const cookieStore = await cookies();
    cookieStore.delete(ADMIN_AUTH_COOKIE);
    redirect("/admin/login");
}
