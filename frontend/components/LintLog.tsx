"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, GitCommit } from "lucide-react";
import { getHistory, type Commit } from "@/lib/api";
import { cn } from "@/lib/cn";

interface LintLogProps {
  notebookId: string;
}

export function LintLog({ notebookId }: LintLogProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["history", notebookId, "lint-fix"],
    queryFn: () => getHistory(notebookId, { limit: 100 }),
    enabled: !!notebookId,
    retry: 0,
  });

  const lintCommits = useMemo(() => {
    return (data ?? []).filter((c) => /\[lint-fix\]/i.test(c.subject ?? ""));
  }, [data]);

  if (!notebookId) return null;
  return (
    <div className="space-y-1">
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide px-1">
        Recent lint runs
      </h3>
      {isLoading ? (
        <div className="text-xs text-muted-foreground italic px-1">Loading…</div>
      ) : lintCommits.length === 0 ? (
        <div className="text-xs text-muted-foreground italic px-1">No lint commits yet.</div>
      ) : (
        <ul className="space-y-1">
          {lintCommits.map((c) => (
            <CommitRow key={c.sha} commit={c} />
          ))}
        </ul>
      )}
    </div>
  );
}

function CommitRow({ commit }: { commit: Commit }) {
  const [open, setOpen] = useState(false);
  const fixCount = (commit.files_changed ?? []).length;
  return (
    <li className="rounded-md border border-border/60 bg-card/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-muted/40 transition-colors"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
        )}
        <GitCommit className="w-3.5 h-3.5 text-fuchsia-500 shrink-0" />
        <span className="font-mono text-[10px] text-muted-foreground">{commit.sha.slice(0, 7)}</span>
        <span className="flex-1 text-left truncate">{commit.subject}</span>
        <span className="text-muted-foreground text-[10px]">
          {fixCount} {fixCount === 1 ? "fix" : "fixes"}
        </span>
      </button>
      {open && (
        <div className="px-2 pb-2 pt-1 border-t border-border/60 space-y-1">
          <pre className={cn("text-[11px] whitespace-pre-wrap font-mono text-muted-foreground")}>
            {commit.body || "(no body)"}
          </pre>
          {(commit.files_changed ?? []).length > 0 && (
            <ul className="text-[11px] text-foreground/80 list-disc pl-4">
              {commit.files_changed.map((p) => (
                <li key={p} className="truncate">{p}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}
