import type { Metadata } from "next";
import "./globals.css";
import { AuthGate } from "../components/AuthGate";
import { AuthProvider } from "../lib/auth";

export const metadata: Metadata = {
  title: "Decision Harness",
  description: "A configurable AI decision council that debates, out loud, with a full audit trail.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <AuthGate>{children}</AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}
