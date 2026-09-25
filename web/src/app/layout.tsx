import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AIRA Hosted",
  description: "Evidence-grounded incident triage for operational teams.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
