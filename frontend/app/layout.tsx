import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { ModeNav } from "@/components/ModeNav";
import { NotebookSwitcher } from "@/components/NotebookSwitcher";
import { AgentStatusBadge } from "@/components/AgentStatusBadge";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "NotebookAI",
  description:
    "A local-first knowledge notebook with Read, Ask, and Curate modes.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body className="bg-background text-foreground min-h-screen flex flex-col">
        <Providers>
          <header className="h-14 border-b border-border bg-background/85 backdrop-blur sticky top-0 z-30 flex items-center px-4 gap-4">
            <div className="flex items-center gap-2">
              <span className="inline-flex w-7 h-7 items-center justify-center rounded-md bg-accent text-accent-foreground text-sm font-semibold tracking-tight">
                N
              </span>
              <span className="text-sm font-semibold tracking-tight">
                NotebookAI
              </span>
            </div>
            <NotebookSwitcher />
            <div className="flex-1" />
            <AgentStatusBadge />
            <ModeNav />
          </header>
          <main className="flex-1 min-h-0 flex flex-col">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
