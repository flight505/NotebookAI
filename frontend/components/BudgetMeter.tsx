"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Pencil } from "lucide-react";
import { http } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/cn";

interface BudgetSnapshot {
  notebook_id: string;
  day: string;
  input_tokens_used: number;
  output_tokens_used: number;
  input_limit: number;
  output_limit: number;
  last_op_at: string | null;
  denied_op_count: number;
}

const DEFAULT_INPUT = 50_000;
const DEFAULT_OUTPUT = 10_000;

async function fetchBudget(notebookId: string): Promise<BudgetSnapshot> {
  const { data } = await http.get<BudgetSnapshot>(`/notebooks/${notebookId}/lint/budget`);
  return data;
}

async function updateBudget(
  notebookId: string,
  body: { input_limit?: number; output_limit?: number },
): Promise<BudgetSnapshot> {
  const { data } = await http.post<BudgetSnapshot>(
    `/notebooks/${notebookId}/lint/budget`,
    body,
  );
  return data;
}

interface BudgetMeterProps {
  notebookId: string;
}

export function BudgetMeter({ notebookId }: BudgetMeterProps) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["lint-budget", notebookId],
    queryFn: () => fetchBudget(notebookId),
    enabled: !!notebookId,
    refetchInterval: 15_000,
    retry: 0,
  });

  const reset = useMutation({
    mutationFn: () =>
      updateBudget(notebookId, {
        input_limit: DEFAULT_INPUT,
        output_limit: DEFAULT_OUTPUT,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lint-budget", notebookId] }),
  });

  const updater = useMutation({
    mutationFn: (body: { input_limit?: number; output_limit?: number }) =>
      updateBudget(notebookId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lint-budget", notebookId] }),
  });

  const [editing, setEditing] = useState(false);
  const [inputLimit, setInputLimit] = useState<number>(DEFAULT_INPUT);
  const [outputLimit, setOutputLimit] = useState<number>(DEFAULT_OUTPUT);

  const inputPct = useMemo(() => percent(data?.input_tokens_used, data?.input_limit), [data]);
  const outputPct = useMemo(() => percent(data?.output_tokens_used, data?.output_limit), [data]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Today's lint budget
        </h3>
        <div className="flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            aria-label="Edit limits"
            onClick={() => {
              setInputLimit(data?.input_limit ?? DEFAULT_INPUT);
              setOutputLimit(data?.output_limit ?? DEFAULT_OUTPUT);
              setEditing(true);
            }}
          >
            <Pencil className="w-3.5 h-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Reset to defaults"
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>
      {isLoading ? (
        <div className="text-xs text-muted-foreground italic">Loading…</div>
      ) : data ? (
        <div className="space-y-3">
          <Bar
            label="Input"
            used={data.input_tokens_used}
            limit={data.input_limit}
            pct={inputPct}
          />
          <Bar
            label="Output"
            used={data.output_tokens_used}
            limit={data.output_limit}
            pct={outputPct}
          />
          {data.denied_op_count > 0 && (
            <p className="text-[11px] text-amber-500">
              {data.denied_op_count} op{data.denied_op_count === 1 ? "" : "s"} denied today
            </p>
          )}
        </div>
      ) : (
        <div className="text-xs text-muted-foreground italic">No data.</div>
      )}

      <Modal
        open={editing}
        onClose={() => setEditing(false)}
        title="Edit lint budget"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            updater.mutate({ input_limit: inputLimit, output_limit: outputLimit });
            setEditing(false);
          }}
          className="space-y-3"
        >
          <label className="block text-sm">
            <span className="text-muted-foreground">Input tokens / day</span>
            <input
              type="number"
              min={0}
              value={inputLimit}
              onChange={(e) => setInputLimit(Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-muted-foreground">Output tokens / day</span>
            <input
              type="number"
              min={0}
              value={outputLimit}
              onChange={(e) => setOutputLimit(Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm"
            />
          </label>
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="outline" size="sm" onClick={() => setEditing(false)}>
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

function percent(used: number | undefined, limit: number | undefined): number {
  if (!limit || limit <= 0) return used && used > 0 ? 100 : 0;
  if (used == null) return 0;
  return Math.max(0, Math.min(100, Math.round((used / limit) * 100)));
}

function Bar({
  label,
  used,
  limit,
  pct,
}: {
  label: string;
  used: number;
  limit: number;
  pct: number;
}) {
  const tone =
    pct < 50
      ? "bg-emerald-500"
      : pct < 90
      ? "bg-amber-500"
      : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono text-foreground/80">
          {used.toLocaleString()} / {limit.toLocaleString()}
        </span>
      </div>
      <div className="h-2 rounded-full bg-subtle overflow-hidden">
        <div
          className={cn("h-full transition-all duration-300", tone)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
