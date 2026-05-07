"use client";

import { Suspense, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Filter, Sparkles, Wand2 } from "lucide-react";
import { http, lint } from "@/lib/api";
import { useNotebookStore } from "@/store/useNotebook";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ActivityStream } from "@/components/ActivityStream";
import { FindingCard, type FindingShape } from "@/components/FindingCard";
import { BudgetMeter } from "@/components/BudgetMeter";
import { LintScheduleIndicator } from "@/components/LintScheduleIndicator";
import { LintLog } from "@/components/LintLog";
import { cn } from "@/lib/cn";

export const dynamic = "force-dynamic";

interface RawFinding {
  id: string;
  notebook_id: string;
  kind: string;
  status: "open" | "accepted" | "rejected" | "auto_fixed" | "resolved";
  payload?: Record<string, any> | null;
}

async function fetchFindings(notebookId: string): Promise<RawFinding[]> {
  const { data } = await http.get<RawFinding[]>(
    `/notebooks/${notebookId}/lint/findings`,
  );
  return data;
}

async function resolveFinding(
  notebookId: string,
  findingId: string,
  action: "accept" | "reject",
): Promise<RawFinding> {
  const { data } = await http.post<RawFinding>(
    `/notebooks/${notebookId}/lint/findings/${findingId}/resolve`,
    { action },
  );
  return data;
}

export default function CuratePage() {
  return (
    <Suspense fallback={<CurateSkeleton />}>
      <CurateShell />
    </Suspense>
  );
}

function CurateShell() {
  const notebookId = useNotebookStore((s) => s.currentNotebookId);
  const qc = useQueryClient();
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  const findingsQuery = useQuery({
    queryKey: ["findings", notebookId],
    queryFn: () => (notebookId ? fetchFindings(notebookId) : Promise.resolve([])),
    enabled: !!notebookId,
    refetchInterval: 10_000,
    retry: 0,
  });

  const triggerLint = useMutation({
    mutationFn: (mode: "light" | "full") => {
      if (!notebookId) return Promise.reject(new Error("no notebook"));
      return http.post(`/notebooks/${notebookId}/lint`, { mode }).then((r) => r.data);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["findings", notebookId] }),
  });

  const accept = useMutation({
    mutationFn: (id: string) => resolveFinding(notebookId!, id, "accept"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["findings", notebookId] });
      qc.invalidateQueries({ queryKey: ["history", notebookId, "lint-fix"] });
    },
  });
  const reject = useMutation({
    mutationFn: (id: string) => resolveFinding(notebookId!, id, "reject"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["findings", notebookId] }),
  });

  const filtered = useMemo(() => {
    const all = findingsQuery.data ?? [];
    return all
      .filter((f) => f.status === "open")
      .filter((f) => kindFilter === "all" || f.kind === kindFilter)
      .filter((f) => {
        if (sourceFilter === "all") return true;
        return (f.payload?.source ?? "passive") === sourceFilter;
      });
  }, [findingsQuery.data, kindFilter, sourceFilter]);

  const kinds = useMemo(() => {
    const set = new Set<string>();
    (findingsQuery.data ?? []).forEach((f) => set.add(f.kind));
    return Array.from(set).sort();
  }, [findingsQuery.data]);

  if (!notebookId) {
    return <NoNotebookEmpty />;
  }

  return (
    <div className="curate-grid grid grid-cols-[320px_minmax(0,1fr)_320px] h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Left: findings list */}
      <aside className="border-r border-border bg-card/40 overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-border flex items-center gap-2">
          <Filter className="w-4 h-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Findings</h2>
          <span className="ml-auto text-xs text-muted-foreground">{filtered.length}</span>
        </div>
        <div className="px-4 py-2 flex flex-col gap-1.5 border-b border-border/60">
          <select
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            className="text-xs rounded-md border border-border bg-card px-2 py-1"
          >
            <option value="all">All kinds</option>
            {kinds.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="text-xs rounded-md border border-border bg-card px-2 py-1"
          >
            <option value="all">All sources</option>
            <option value="passive">passive</option>
            <option value="haiku">haiku</option>
            <option value="user">user</option>
          </select>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {findingsQuery.isLoading ? (
            <Skeleton className="h-16" />
          ) : filtered.length === 0 ? (
            <p className="text-xs text-muted-foreground italic px-1">
              No open findings.
            </p>
          ) : (
            filtered.map((raw) => (
              <FindingCard
                key={raw.id}
                finding={toFindingShape(raw)}
                onAccept={async (id) => {
                  await accept.mutateAsync(id);
                }}
                onReject={async (id) => {
                  await reject.mutateAsync(id);
                }}
              />
            ))
          )}
        </div>
      </aside>

      {/* Center: activity */}
      <section className="overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-border flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-yellow-500" />
          <h2 className="text-sm font-semibold">Activity</h2>
          <div className="ml-auto flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={triggerLint.isPending}
              onClick={() => triggerLint.mutate("light")}
            >
              <Wand2 className="w-3.5 h-3.5" />
              Light lint
            </Button>
            <Button
              size="sm"
              variant="accent"
              disabled={triggerLint.isPending}
              onClick={() => triggerLint.mutate("full")}
            >
              <Wand2 className="w-3.5 h-3.5" />
              Full lint
            </Button>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          <ActivityStream notebookId={notebookId} />
        </div>
      </section>

      {/* Right: budget + history */}
      <aside className={cn(
        "border-l border-border bg-card/40 overflow-y-auto p-4 space-y-6",
      )}>
        <BudgetMeter notebookId={notebookId} />
        <LintScheduleIndicator notebookId={notebookId} />
        <LintLog notebookId={notebookId} />
      </aside>
    </div>
  );
}

function toFindingShape(raw: RawFinding): FindingShape {
  // Normalize legacy "resolved" → "accepted" for rendering.
  const status =
    raw.status === "resolved"
      ? "accepted"
      : (raw.status as FindingShape["status"]);
  return {
    id: raw.id,
    kind: raw.kind,
    status,
    payload: raw.payload as FindingShape["payload"],
  };
}

function NoNotebookEmpty() {
  return (
    <div className="flex flex-1 items-center justify-center text-center p-12">
      <div className="space-y-2 max-w-md">
        <Sparkles className="w-10 h-10 mx-auto text-muted-foreground" />
        <h2 className="text-lg font-semibold">Pick a notebook to curate</h2>
        <p className="text-sm text-muted-foreground">
          The Curate view shows lint findings, the live agent activity feed,
          and today's lint budget.
        </p>
      </div>
    </div>
  );
}

function CurateSkeleton() {
  return (
    <div className="grid grid-cols-3 gap-4 p-6">
      <Skeleton className="h-96" />
      <Skeleton className="h-96" />
      <Skeleton className="h-96" />
    </div>
  );
}
