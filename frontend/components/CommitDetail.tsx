"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { http, API_BASE_URL } from "@/lib/api";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import type { HistoryEntry } from "@/components/HistoryTimeline";

interface CommitDetailResponse extends HistoryEntry {
  diff: string;
}

interface CommitDetailProps {
  notebookId: string;
  sha: string | null;
  onClose: () => void;
}

async function fetchCommit(
  notebookId: string,
  sha: string
): Promise<CommitDetailResponse> {
  const { data } = await http.get<CommitDetailResponse>(
    `/notebooks/${notebookId}/history/${sha}`
  );
  return data;
}

async function revertCommit(
  notebookId: string,
  sha: string
): Promise<CommitDetailResponse> {
  const res = await fetch(
    `${API_BASE_URL}/notebooks/${notebookId}/history/${sha}/revert`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Confirm": "revert",
      },
    }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`revert failed: ${res.status} ${text}`);
  }
  return res.json();
}

export function CommitDetail({
  notebookId,
  sha,
  onClose,
}: CommitDetailProps) {
  const open = !!sha;
  const qc = useQueryClient();
  const [confirmStep, setConfirmStep] = useState<0 | 1 | 2>(0);

  const detailQuery = useQuery({
    queryKey: ["commit", notebookId, sha],
    queryFn: () => fetchCommit(notebookId, sha!),
    enabled: open,
    staleTime: 30_000,
  });

  const revertMu = useMutation({
    mutationFn: () => revertCommit(notebookId, sha!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["history", notebookId] });
      setConfirmStep(0);
      onClose();
    },
  });

  const handleClose = () => {
    setConfirmStep(0);
    revertMu.reset();
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={detailQuery.data?.subject || "Commit"}
      className="max-w-2xl"
    >
      {detailQuery.isLoading ? (
        <Skeleton className="h-64" />
      ) : detailQuery.error ? (
        <p className="text-sm text-red-500">
          Failed to load commit: {(detailQuery.error as Error).message}
        </p>
      ) : detailQuery.data ? (
        <div className="space-y-4 text-sm">
          <header className="space-y-1">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span className="font-mono">{detailQuery.data.sha}</span>
              {detailQuery.data.author && (
                <span>Author: {detailQuery.data.author}</span>
              )}
              {detailQuery.data.created_at && (
                <span>{detailQuery.data.created_at}</span>
              )}
            </div>
            {detailQuery.data.body && (
              <pre className="mt-2 rounded-md border border-border/60 bg-subtle/40 px-3 py-2 text-xs whitespace-pre-wrap font-mono">
                {detailQuery.data.body}
              </pre>
            )}
          </header>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              Files changed ({detailQuery.data.files_changed?.length ?? 0})
            </h3>
            {detailQuery.data.files_changed?.length ? (
              <ul className="text-xs font-mono space-y-1">
                {detailQuery.data.files_changed.map((f) => (
                  <li key={f} className="truncate">
                    {f}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground italic">
                No file changes detected.
              </p>
            )}
            <div className="mt-2 flex gap-3 text-xs">
              {(detailQuery.data.insertions ?? 0) > 0 && (
                <span className="text-emerald-600 dark:text-emerald-400">
                  +{detailQuery.data.insertions}
                </span>
              )}
              {(detailQuery.data.deletions ?? 0) > 0 && (
                <span className="text-red-600 dark:text-red-400">
                  −{detailQuery.data.deletions}
                </span>
              )}
            </div>
          </section>

          {detailQuery.data.diff && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                Diff
              </h3>
              <DiffBlock diff={detailQuery.data.diff} />
            </section>
          )}

          <section className="pt-2 border-t border-border/60">
            {revertMu.error && (
              <p className="text-xs text-red-500 mb-2">
                {(revertMu.error as Error).message}
              </p>
            )}
            {confirmStep === 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirmStep(1)}
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Revert this commit
              </Button>
            )}
            {confirmStep === 1 && (
              <div className="flex items-center gap-2 text-xs">
                <AlertTriangle className="w-4 h-4 text-amber-500" />
                <span>
                  Reverting creates a new inverse commit. Continue?
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmStep(0)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  variant="accent"
                  onClick={() => setConfirmStep(2)}
                >
                  Yes, confirm
                </Button>
              </div>
            )}
            {confirmStep === 2 && (
              <div className="flex items-center gap-2 text-xs">
                <AlertTriangle className="w-4 h-4 text-red-500" />
                <span>This sends X-Confirm: revert. Final confirmation:</span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmStep(0)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  variant="accent"
                  disabled={revertMu.isPending}
                  onClick={() => revertMu.mutate()}
                >
                  {revertMu.isPending ? "Reverting…" : "Revert now"}
                </Button>
              </div>
            )}
          </section>
        </div>
      ) : null}
    </Modal>
  );
}

function DiffBlock({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return (
    <pre className="rounded-md border border-border/60 bg-subtle/40 px-3 py-2 text-xs font-mono overflow-x-auto max-h-80">
      {lines.map((line, i) => {
        let tone = "text-foreground/80";
        if (line.startsWith("+") && !line.startsWith("+++"))
          tone = "text-emerald-500";
        else if (line.startsWith("-") && !line.startsWith("---"))
          tone = "text-red-500";
        else if (line.startsWith("@@")) tone = "text-violet-500";
        else if (line.startsWith("commit ") || line.startsWith("Author"))
          tone = "text-muted-foreground";
        return (
          <div key={i} className={cn("whitespace-pre", tone)}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
