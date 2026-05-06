"use client";

import { useMemo } from "react";
import { FileText, GitCommit } from "lucide-react";
import { cn } from "@/lib/cn";
import { Skeleton } from "@/components/ui/Skeleton";

export interface HistoryEntry {
  sha: string;
  author?: string | null;
  created_at?: string | null;
  subject: string;
  body?: string;
  op?: string | null;
  op_id?: string | null;
  files_changed?: string[];
  insertions?: number;
  deletions?: number;
}

interface HistoryTimelineProps {
  entries: HistoryEntry[];
  loading?: boolean;
  selectedSha?: string | null;
  onSelect: (entry: HistoryEntry) => void;
}

const OP_BADGE: Record<string, { label: string; className: string }> = {
  ingest: {
    label: "ingest",
    className: "bg-blue-500/15 text-blue-600 dark:text-blue-300",
  },
  compile: {
    label: "compile",
    className: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300",
  },
  cascade: {
    label: "cascade",
    className: "bg-violet-500/15 text-violet-600 dark:text-violet-300",
  },
  archive: {
    label: "archive",
    className: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  "lint-fix": {
    label: "lint-fix",
    className: "bg-pink-500/15 text-pink-600 dark:text-pink-300",
  },
  "human-edit": {
    label: "human-edit",
    className: "bg-slate-500/15 text-slate-600 dark:text-slate-300",
  },
};

const FALLBACK_BADGE = {
  label: "op",
  className: "bg-muted text-muted-foreground",
};

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diffMs = Date.now() - t;
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(t).toLocaleDateString();
}

function stripOpPrefix(subject: string): string {
  return subject.replace(/^\[[^\]]+\]\s*/, "");
}

export function HistoryTimeline({
  entries,
  loading,
  selectedSha,
  onSelect,
}: HistoryTimelineProps) {
  const items = useMemo(() => entries ?? [], [entries]);

  if (loading) {
    return (
      <ol className="space-y-3" aria-busy="true">
        {Array.from({ length: 6 }).map((_, i) => (
          <li key={i}>
            <Skeleton className="h-12" />
          </li>
        ))}
      </ol>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center text-center p-12 text-muted-foreground">
        <GitCommit className="w-8 h-8 mb-3 opacity-60" />
        <p className="text-sm font-medium">No operations yet</p>
        <p className="text-xs mt-1 max-w-xs">
          Try ingesting a source — every agent op produces one commit visible
          here.
        </p>
      </div>
    );
  }

  return (
    <ol className="relative pl-5 space-y-2 before:absolute before:left-1.5 before:top-1.5 before:bottom-1.5 before:w-px before:bg-border">
      {items.map((entry) => {
        const op = entry.op || "";
        const badge = OP_BADGE[op] ?? FALLBACK_BADGE;
        const fileCount = entry.files_changed?.length ?? 0;
        const isSel = selectedSha === entry.sha;
        const subject = stripOpPrefix(entry.subject || "");
        return (
          <li key={entry.sha} className="relative group">
            <span
              className={cn(
                "absolute -left-[14px] top-3 w-2.5 h-2.5 rounded-full",
                "ring-2 ring-background",
                isSel ? "bg-accent" : "bg-foreground/40 group-hover:bg-foreground/70"
              )}
              aria-hidden="true"
            />
            <button
              type="button"
              onClick={() => onSelect(entry)}
              className={cn(
                "w-full text-left rounded-md border border-border/60 bg-card/40 p-3 transition-colors",
                "hover:bg-card/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)] focus-visible:outline-offset-2",
                isSel && "border-accent bg-card"
              )}
              title={entry.body || undefined}
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-[10px] font-mono uppercase tracking-wide rounded px-1.5 py-0.5",
                    badge.className
                  )}
                >
                  {op || badge.label}
                </span>
                <span className="text-sm font-medium truncate flex-1 min-w-0">
                  {subject || "(no subject)"}
                </span>
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  {relativeTime(entry.created_at)}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                <span className="font-mono">{entry.sha.slice(0, 8)}</span>
                {fileCount > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <FileText className="w-3 h-3" />
                    {fileCount} {fileCount === 1 ? "file" : "files"}
                  </span>
                )}
                {(entry.insertions ?? 0) > 0 && (
                  <span className="text-emerald-600 dark:text-emerald-400">
                    +{entry.insertions}
                  </span>
                )}
                {(entry.deletions ?? 0) > 0 && (
                  <span className="text-red-600 dark:text-red-400">
                    −{entry.deletions}
                  </span>
                )}
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
