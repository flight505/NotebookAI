"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Bot, User, X, Check, FileText } from "lucide-react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";

export interface FindingShape {
  id: string;
  kind: string;
  status: "open" | "accepted" | "rejected" | "auto_fixed";
  payload?: {
    path?: string;
    message?: string;
    suggested_fix?: string | null;
    source?: "passive" | "haiku" | "user";
  } | null;
}

interface FindingCardProps {
  finding: FindingShape;
  onAccept?: (id: string) => Promise<void> | void;
  onReject?: (id: string) => Promise<void> | void;
}

const SOURCE_ICON: Record<string, any> = {
  passive: FileText,
  haiku: Sparkles,
  user: User,
};

const SOURCE_LABEL: Record<string, string> = {
  passive: "passive",
  haiku: "haiku",
  user: "user",
};

export function FindingCard({ finding, onAccept, onReject }: FindingCardProps) {
  const payload = finding.payload ?? {};
  const source = payload.source ?? "passive";
  const SourceIcon = SOURCE_ICON[source] ?? Bot;
  const [resolving, setResolving] = useState<"accept" | "reject" | null>(null);
  const [hidden, setHidden] = useState(false);
  const dimmed = finding.status !== "open" || resolving !== null;

  const handle = async (action: "accept" | "reject") => {
    if (!finding || resolving) return;
    setResolving(action);
    try {
      if (action === "accept") {
        await onAccept?.(finding.id);
      } else {
        await onReject?.(finding.id);
      }
      // Animate collapse and remove
      setTimeout(() => setHidden(true), 350);
    } catch (err) {
      console.error("finding resolve failed", err);
      setResolving(null);
    }
  };

  return (
    <AnimatePresence initial={false}>
      {!hidden && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{
            opacity: dimmed ? 0.55 : 1,
            y: 0,
            height: "auto",
          }}
          exit={{ opacity: 0, height: 0, marginBottom: 0, paddingTop: 0, paddingBottom: 0 }}
          transition={{ duration: 0.25 }}
          className="rounded-lg border border-border bg-card overflow-hidden"
          data-testid="finding-card"
          data-finding-id={finding.id}
          data-finding-status={finding.status}
        >
          <div className="px-4 py-3 flex items-center gap-2 border-b border-border/60">
            <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-subtle text-foreground/80">
              {finding.kind}
            </span>
            <span className="text-xs text-muted-foreground">
              {payload.path ?? ""}
            </span>
            <span className="ml-auto inline-flex items-center gap-1 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-subtle text-muted-foreground">
              <SourceIcon className="w-3 h-3" />
              {SOURCE_LABEL[source] ?? source}
            </span>
          </div>
          <div className="px-4 py-3 space-y-3">
            <p className="text-sm text-foreground/90">{payload.message ?? ""}</p>
            {payload.suggested_fix ? (
              <DiffPreview suggestion={payload.suggested_fix} />
            ) : null}
            <div className="flex gap-2 pt-1">
              <Button
                size="sm"
                variant="accent"
                disabled={dimmed}
                onClick={() => handle("accept")}
                data-testid="finding-accept"
              >
                <Check className="w-3.5 h-3.5" />
                Accept
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={dimmed}
                onClick={() => handle("reject")}
                data-testid="finding-reject"
              >
                <X className="w-3.5 h-3.5" />
                Reject
              </Button>
              {finding.status !== "open" && (
                <span className="ml-auto text-xs text-muted-foreground italic">
                  {finding.status}
                </span>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * Lightweight before/after diff: split the suggestion on `---` if present,
 * else just show it as a code block. Avoids a heavyweight diff library.
 */
function DiffPreview({ suggestion }: { suggestion: string }) {
  const trimmed = suggestion.trim();
  // Look for a unified-diff-ish pattern with --- / +++ separators or +/- prefixed lines.
  const hasDiff = /^[+\-]/m.test(trimmed);
  if (!hasDiff) {
    return (
      <pre className="rounded-md border border-border/60 bg-subtle/40 px-3 py-2 text-xs whitespace-pre-wrap font-mono">
        {trimmed}
      </pre>
    );
  }
  return (
    <pre className="rounded-md border border-border/60 bg-subtle/40 px-3 py-2 text-xs font-mono overflow-x-auto">
      {trimmed.split("\n").map((line, i) => {
        const tone = line.startsWith("+")
          ? "text-emerald-500"
          : line.startsWith("-")
          ? "text-red-500"
          : "text-foreground/80";
        return (
          <div key={i} className={cn("whitespace-pre", tone)}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
