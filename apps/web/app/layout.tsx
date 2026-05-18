import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
    title: "Digital Twin Command Center",
    description: "Behavioral mirror prototype with token-based participant sessions.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
    return (
        <html lang="en">
            <body>{children}</body>
        </html>
    );
}