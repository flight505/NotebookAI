"use client";

import { Suspense, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { GitCommit, History as HistoryIcon } from "lucide-react";
import { http } from "@/lib/api";
import { useNotebookStore } from "@/store/useNotebook";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  HistoryTimeline,
  type HistoryEntry,
} from "@/components/HistoryTimeline";
import { CommitDetail } from "@/components/CommitDetail";
import { cn } from "@/lib/cn";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;
const OPS = [
  "all",
  "ingest",
  "compile",
  "cascade",
  "archive",
  "lint-fix",
  "human-edit",
] as const;
type OpFilter = (typeof OPS)[number];

interface PageState {
  op: OpFilter;
  cursor: string | null;
}

async function fetchHistory(
  notebookId: string,
  state: PageState
): Promise<HistoryEntry[]> {
  const params: Record<string, string | number> = { limit: PAGE_SIZE };
  if (state.op !== "all") params.op = state.op;
  if (state.cursor) params.since_sha = state.cursor;
  const { data } = await http.get<HistoryEntry[]>(
    `/notebooks/${notebookId}/history`,
    { params }
  );
  return data;
}

export default function HistoryPage() {
  return (
    <Suspense fallback={<HistorySkeleton />}>
      <HistoryShell />
    </Suspense>
  );
}

function HistoryShell() {
  const notebookId = useNotebookStore((s) => s.currentNotebookId);
  const [op, setOp] = useState<OpFilter>("all");
  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedSha, setSelectedSha] = useState<string | null>(null);

  const historyQuery = useQuery({
    queryKey: ["history", notebookId, op, cursor],
    queryFn: () =>
      notebookId ? fetchHistory(notebookId, { op, cursor }) : Promise.resolve([]),
    enabled: !!notebookId,
  });

  const entries = useMemo(
    () => historyQuery.data ?? [],
    [historyQuery.data]
  );

  if (!notebookId) {
    return <NoNotebookEmpty />;
  }

  const oldestSha = entries.length ? entries[entries.length - 1].sha : null;

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-4">
      <header className="flex items-center gap-3">
        <HistoryIcon className="w-5 h-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold tracking-tight">
          Operation history
        </h1>
        <span className="ml-auto text-xs text-muted-foreground">
          {entries.length} entr{entries.length === 1 ? "y" : "ies"}
        </span>
      </header>

      <div className="flex flex-wrap gap-2">
        {OPS.map((o) => (
          <button
            key={o}
            onClick={() => {
              setOp(o);
              setCursor(null);
            }}
            className={cn(
              "px-2.5 py-1 rounded-full text-xs font-medium border transition-colors",
              op === o
                ? "bg-foreground text-background border-foreground"
                : "border-border bg-card hover:bg-muted text-muted-foreground"
            )}
          >
            {o}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-border bg-card/30 p-4">
        <HistoryTimeline
          entries={entries}
          loading={historyQuery.isLoading}
          selectedSha={selectedSha}
          onSelect={(e) => setSelectedSha(e.sha)}
        />
      </div>

      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          disabled={!cursor}
          onClick={() => setCursor(null)}
        >
          Reset to newest
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!oldestSha || entries.length < PAGE_SIZE}
          onClick={() => oldestSha && setCursor(oldestSha)}
        >
          <GitCommit className="w-3.5 h-3.5" />
          Older commits
        </Button>
      </div>

      <CommitDetail
        notebookId={notebookId}
        sha={selectedSha}
        onClose={() => setSelectedSha(null)}
      />
    </div>
  );
}

function NoNotebookEmpty() {
  return (
    <div className="flex flex-1 items-center justify-center text-center p-12">
      <div className="space-y-2 max-w-md">
        <HistoryIcon className="w-10 h-10 mx-auto text-muted-foreground" />
        <h2 className="text-lg font-semibold">Pick a notebook</h2>
        <p className="text-sm text-muted-foreground">
          Operation history is per-notebook. Select one in the switcher to view
          the commit timeline.
        </p>
      </div>
    </div>
  );
}

function HistorySkeleton() {
  return (
    <div className="max-w-3xl mx-auto p-6 space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-10" />
      <Skeleton className="h-96" />
    </div>
  );
}
