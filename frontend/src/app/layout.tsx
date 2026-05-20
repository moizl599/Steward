import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist, Geist_Mono, JetBrains_Mono } from "next/font/google";
import { Providers } from "./providers";
import { Sidebar } from "@/components/sidebar";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  weight: ["700", "800"],
});

export const metadata: Metadata = {
  title: "Steward — local FinOps for Kubernetes",
  description: "Local-first FinOps reports for Kubernetes. Reads Kubecost data, analyzes with a local LLM, ships prioritized findings — without sending cluster data outside your environment.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geist.variable} ${geistMono.variable} ${jetbrainsMono.variable}`}
    >
      <body className="min-h-screen antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 overflow-x-hidden">{children}</main>
          </div>
          <Toaster position="bottom-right" />
        </Providers>
      </body>
    </html>
  );
}
