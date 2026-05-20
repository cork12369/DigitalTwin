import Link from "next/link";

import { TokenStartForm } from "./token-start-form";

export default function StartPage() {
    return (
        <main className="page">
            <div className="container start-layout">
                <section className="hero">
                    <span className="eyebrow">Initialize Twin</span>
                    <h1>Enter your access token.</h1>
                    <p>
                        Use the token generated from the admin dashboard. After it is accepted, your questionnaire
                        session starts immediately.
                    </p>
                    <Link className="button secondary" href="/">Back Home</Link>
                </section>

                <TokenStartForm />
            </div>
        </main>
    );
}
