"use client";

import { ReactNode, useEffect, useRef, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import toast, { Toaster } from "react-hot-toast";
import { subscribeEvents } from "@/lib/api";
import { useNotebookStore } from "@/store/useNotebook";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  const theme = useNotebookStore((s) => s.theme);
  const notebookId = useNotebookStore((s) => s.currentNotebookId);

  useEffect(() => {
    const root = document.documentElement;
    const apply = (t: "light" | "dark") => {
      if (t === "dark") root.classList.add("dark");
      else root.classList.remove("dark");
    };
    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      apply(mq.matches ? "dark" : "light");
      const handler = (e: MediaQueryListEvent) =>
        apply(e.matches ? "dark" : "light");
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    } else {
      apply(theme);
    }
  }, [theme]);

  // Surface a one-time toast when the agent goes into wiki-only mode while
  // the user is active. The badge in the top nav stays visible afterwards.
  return (
    <QueryClientProvider client={client}>
      <_AgentUnavailableToaster notebookId={notebookId} client={client} />
      {children}
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "var(--card)",
            color: "var(--foreground)",
            border: "1px solid var(--border)",
            fontSize: "0.875rem",
          },
        }}
      />
    </QueryClientProvider>
  );
}

function _AgentUnavailableToaster({
  notebookId,
  client,
}: {
  notebookId: string | null;
  client: QueryClient;
}) {
  const seenRef = useRef(false);

  useEffect(() => {
    if (!notebookId) return;
    seenRef.current = false;
    const sub = subscribeEvents(notebookId, (event, data) => {
      if (event !== "agent.unavailable") return;
      // Refresh cached agent status so the badge updates.
      client.invalidateQueries({ queryKey: ["agent-status", notebookId] });
      if (seenRef.current) return;
      seenRef.current = true;
      const reason =
        (data && typeof data.reason === "string" && data.reason) ||
        "Claude is unavailable — running in wiki-only mode.";
      toast(reason, { icon: "⚠️", duration: 6000 });
    });
    return () => sub.close();
  }, [notebookId, client]);

  return null;
}
