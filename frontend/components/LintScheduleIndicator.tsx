"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Play, Settings as SettingsIcon } from "lucide-react";
import {
  getLintSchedule,
  triggerLintNow,
  updateLintSchedule,
  type LintScheduleStatus,
} from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/cn";

const INTERVAL_OPTIONS = [5, 15, 30, 60, 120, 360] as const;

interface LintScheduleIndicatorProps {
  notebookId: string;
}

export function LintScheduleIndicator({ notebookId }: LintScheduleIndicatorProps) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<LintScheduleStatus>({
    queryKey: ["lint-schedule", notebookId],
    queryFn: () => getLintSchedule(notebookId),
    enabled: !!notebookId,
    refetchInterval: 30_000,
    retry: 0,
  });

  const updater = useMutation({
    mutationFn: (body: { enabled?: boolean; interval_minutes?: number }) =>
      updateLintSchedule(notebookId, body),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["lint-schedule", notebookId] }),
  });

  const runNow = useMutation({
    mutationFn: () => triggerLintNow(notebookId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["lint-schedule", notebookId] }),
  });

  const [editing, setEditing] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [interval, setInterval] = useState<number>(60);

  // Local clock so the countdown ticks every second between 30s polls.
  const [now, setNow] = useState<number>(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(id);
  }, []);

  const countdown = useMemo(() => {
    if (!data?.enabled || data.next_run_at == null) return null;
    const seconds = Math.max(0, Math.round(data.next_run_at - now));
    return formatCountdown(seconds);
  }, [data, now]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Scheduled lint
        </h3>
        <div className="flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            aria-label="Run lint now"
            disabled={runNow.isPending}
            onClick={() => runNow.mutate()}
          >
            <Play className="w-3.5 h-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Schedule settings"
            onClick={() => {
              setEnabled(data?.enabled ?? true);
              setInterval(data?.interval_minutes ?? 60);
              setEditing(true);
            }}
          >
            <SettingsIcon className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="text-xs text-muted-foreground italic">Loading…</div>
      ) : data?.enabled === false ? (
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full bg-subtle px-2 py-0.5 text-[11px]",
            "text-muted-foreground"
          )}
        >
          <Clock className="w-3 h-3" />
          Disabled
        </span>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-sm">
            <Clock className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="font-mono text-foreground/90">
              Next: {countdown ?? "—"}
            </span>
            {data?.running && (
              <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-emerald-500">
                Running…
              </span>
            )}
          </div>
          <div className="text-[11px] text-muted-foreground">
            Every {data?.interval_minutes ?? 60} min
            {typeof data?.last_finding_count === "number" && (
              <> · last run: {data.last_finding_count} findings</>
            )}
            {data?.last_result === "skipped" && data?.last_skip_reason && (
              <> · skipped ({data.last_skip_reason})</>
            )}
          </div>
        </div>
      )}

      <Modal
        open={editing}
        onClose={() => setEditing(false)}
        title="Lint schedule"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            updater.mutate({ enabled, interval_minutes: interval });
            setEditing(false);
          }}
          className="space-y-4"
        >
          <label className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Enabled</span>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
          </label>
          <label className="block text-sm">
            <span className="text-muted-foreground">Interval</span>
            <select
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
            >
              {INTERVAL_OPTIONS.map((m) => (
                <option key={m} value={m}>
                  {m < 60 ? `${m} min` : `${m / 60} h`}
                </option>
              ))}
            </select>
          </label>
          <div className="flex gap-2 justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
            <Button type="submit" variant="accent" size="sm">
              Save
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "now";
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return `in ${h}h ${m}m`;
  }
  if (minutes >= 1) {
    return `in ${minutes}m`;
  }
  return `in ${secs}s`;
}
