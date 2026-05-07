"use client";

import { motion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { http } from "@/lib/api";
import { Button } from "@/components/ui/Button";

interface AgentStatus {
  available: boolean;
  reason: string | null;
}

interface NotebookWithStatus {
  id: string;
  name: string;
  agent: { model: string };
  agent_status?: AgentStatus;
}

async function fetchNotebookStatus(id: string): Promise<NotebookWithStatus> {
  const { data } = await http.get<NotebookWithStatus>(`/notebooks/${id}`);
  return data;
}

interface Props {
  notebookId: string;
  onFinish: () => void;
}

/**
 * Step 3 — verify Claude availability for the just-created notebook.
 *
 * Polls `/api/notebooks/{id}` every 3s while the agent is unavailable so
 * users who set credentials in another window can hit "Get started"
 * without restarting the flow.
 */
export function WelcomeStep3({ notebookId, onFinish }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["notebook-status", notebookId],
    queryFn: () => fetchNotebookStatus(notebookId),
    refetchInterval: (q) => (q.state.data?.agent_status?.available ? false : 3000),
  });

  const status = data?.agent_status;
  const available = status?.available ?? false;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2 }}
      className="px-6 w-full max-w-xl"
      data-testid="welcome-step-3"
    >
      <div className="text-center mb-6">
        <h2 className="text-xl font-semibold tracking-tight mb-2">
          Verify Claude availability
        </h2>
        <p className="text-sm text-muted-foreground">
          NotebookAI works with or without Claude. Here's what we detected.
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          Checking agent status…
        </div>
      ) : available ? (
        <div
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 mb-6"
          data-testid="welcome-status-available"
        >
          <div className="flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-semibold text-emerald-900 dark:text-emerald-100 mb-1">
                You're set!
              </p>
              <p className="text-emerald-800/80 dark:text-emerald-200/80">
                Claude credentials detected. Using model{" "}
                <code className="font-mono text-xs px-1 py-0.5 rounded bg-emerald-500/10">
                  {data?.agent?.model ?? "claude-sonnet-4-6"}
                </code>
                . Ingest, ask, and lint operations are fully enabled.
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div
          className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 mb-6"
          data-testid="welcome-status-unavailable"
        >
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-semibold text-amber-900 dark:text-amber-100 mb-1">
                Wiki-only mode
              </p>
              <p className="text-amber-800/80 dark:text-amber-200/80 mb-2">
                {status?.reason ??
                  "Claude credentials not found. NotebookAI will run in wiki-only mode: ingest still saves raw markdown, ask returns retrieval-only answers, and lint runs the passive watcher only."}
              </p>
              <a
                href="https://github.com/flight505/NotebookAI/blob/main/docs/wiki-only-mode.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-amber-900 dark:text-amber-100 underline underline-offset-2 hover:no-underline"
              >
                Read about wiki-only mode →
              </a>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-center">
        <Button
          variant="accent"
          onClick={onFinish}
          data-testid="welcome-finish"
        >
          Get started
        </Button>
      </div>
    </motion.div>
  );
}
