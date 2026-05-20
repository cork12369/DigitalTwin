import Link from "next/link";

import { AdminLoginForm } from "./login-form";

type PageProps = {
    searchParams?: Promise<{ next?: string }>;
};

export default async function AdminLoginPage({ searchParams }: PageProps) {
    const params = await searchParams;
    const next = params?.next?.startsWith("/admin") ? params.next : "/admin";

    return (
        <main className="page">
            <div className="container stack">
                <section className="hero">
                    <span className="eyebrow">Admin Lock</span>
                    <h1>Enter the admin secret.</h1>
                    <p>Access to the command center, token keys, and evidence browser is password protected.</p>
                    <div className="row" style={{ justifyContent: "flex-start" }}>
                        <Link className="button secondary" href="/">Back Home</Link>
                    </div>
                </section>

                <section className="panel stack">
                    <h2>Admin Login</h2>
                    <AdminLoginForm next={next} />
                </section>
            </div>
        </main>
    );
}
