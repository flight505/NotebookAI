"use client";

import { useQuery } from "@tanstack/react-query";
import { http } from "@/lib/api";
import { useNotebookStore } from "@/store/useNotebook";
import { cn } from "@/lib/cn";

interface AgentStatusPayload {
  available: boolean;
  reason: string | null;
}

interface NotebookWithStatus {
  id: string;
  agent_status?: AgentStatusPayload;
}

async function fetchNotebookStatus(
  id: string,
): Promise<AgentStatusPayload | null> {
  const { data } = await http.get<NotebookWithStatus>(`/notebooks/${id}`);
  return data.agent_status ?? null;
}

/**
 * Small pill in the top nav showing whether the Claude agent is available.
 *
 * Reads `agent_status` from `GET /api/notebooks/{id}` (cached 30s by the
 * default react-query staleTime in `Providers`). No polling — degraded mode
 * changes are picked up via the global `agent.unavailable` SSE event by
 * invalidating this query.
 */
export function AgentStatusBadge() {
  const notebookId = useNotebookStore((s) => s.currentNotebookId);

  const { data } = useQuery({
    queryKey: ["agent-status", notebookId],
    queryFn: () =>
      notebookId ? fetchNotebookStatus(notebookId) : Promise.resolve(null),
    enabled: !!notebookId,
  });

  if (!notebookId || !data) return null;

  const available = data.available;
  const tooltip = available
    ? "Claude credentials detected. Ingest, ask, and lint use the agent."
    : (data.reason ??
        "Wiki-only mode: ingest writes raw files, ask returns retrieved chunks, lint runs passive checks only.");

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
        available
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
      )}
      title={tooltip}
      role="status"
      aria-label={available ? "Claude ready" : "Wiki-only mode"}
    >
      <span
        className={cn(
          "inline-block h-1.5 w-1.5 rounded-full",
          available ? "bg-emerald-500" : "bg-amber-500",
        )}
      />
      {available ? "Claude ready" : "Wiki-only mode"}
      {!available && (
        <a
          href="/docs/wiki-only-mode.md"
          target="_blank"
          rel="noreferrer"
          className="ml-1 underline-offset-2 hover:underline"
        >
          How to enable
        </a>
      )}
    </div>
  );
}
