"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Hammer,
  MessageSquare,
  Check,
  AlertTriangle,
  FileText,
  GitCommit,
  Sparkles,
  Pause,
  Play,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { subscribeEvents } from "@/lib/api";
import { cn } from "@/lib/cn";

export interface ActivityEvent {
  id: string;
  receivedAt: number;
  event: string;
  op_id?: string;
  data: Record<string, any>;
}

const ICONS: Record<string, { icon: any; tone: string }> = {
  "agent.tool_call": { icon: Hammer, tone: "text-amber-500" },
  "agent.tool_result": { icon: Hammer, tone: "text-amber-500/70" },
  "agent.message": { icon: MessageSquare, tone: "text-sky-500" },
  "agent.done": { icon: Check, tone: "text-emerald-500" },
  "agent.error": { icon: AlertTriangle, tone: "text-red-500" },
  "file.changed": { icon: FileText, tone: "text-violet-500" },
  "commit.created": { icon: GitCommit, tone: "text-fuchsia-500" },
  "lint.finding": { icon: Sparkles, tone: "text-yellow-500" },
};

interface ActivityStreamProps {
  notebookId: string;
}

export function ActivityStream({ notebookId }: ActivityStreamProps) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const counter = useRef(0);

  useEffect(() => {
    if (!notebookId) return;
    const sub = subscribeEvents(notebookId, (eventName, data) => {
      counter.current += 1;
      const id = `${Date.now()}-${counter.current}`;
      const op_id =
        typeof data?.op_id === "string" ? (data.op_id as string) : undefined;
      setEvents((prev) => {
        const next = [...prev, { id, receivedAt: Date.now(), event: eventName, op_id, data }];
        return next.slice(-200);
      });
    });
    return () => sub.close();
  }, [notebookId]);

  const effectivePause = paused || hovered;

  // Auto-scroll to bottom unless paused/hovered.
  useEffect(() => {
    if (effectivePause) return;
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length, effectivePause]);

  // Group consecutive events from same op_id into collapsible cards.
  const groups = useMemo(() => groupEvents(events), [events]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className={cn("w-2 h-2 rounded-full", paused ? "bg-amber-500" : "bg-emerald-500 animate-pulse")} />
          <span>{paused ? "Paused" : hovered ? "Hover paused" : "Live"}</span>
        </div>
        <button
          onClick={() => setPaused((p) => !p)}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          aria-label={paused ? "Resume" : "Pause"}
        >
          {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
          {paused ? "Resume" : "Pause"}
        </button>
      </div>
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        data-testid="activity-stream"
      >
        {groups.length === 0 ? (
          <div className="text-xs text-muted-foreground italic py-8 text-center">
            Waiting for agent activity…
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {groups.map((g) =>
              g.kind === "single" ? (
                <ActivityRow key={g.event.id} event={g.event} />
              ) : (
                <GroupCard key={g.opId} opId={g.opId} events={g.events} />
              )
            )}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

type Group =
  | { kind: "single"; event: ActivityEvent }
  | { kind: "group"; opId: string; events: ActivityEvent[] };

function groupEvents(events: ActivityEvent[]): Group[] {
  const out: Group[] = [];
  let bucket: ActivityEvent[] = [];
  let bucketOp: string | undefined;
  const flush = () => {
    if (!bucket.length) return;
    if (bucketOp && bucket.length > 1) {
      out.push({ kind: "group", opId: bucketOp, events: bucket });
    } else {
      bucket.forEach((e) => out.push({ kind: "single", event: e }));
    }
    bucket = [];
    bucketOp = undefined;
  };
  for (const ev of events) {
    if (!ev.op_id) {
      flush();
      out.push({ kind: "single", event: ev });
      continue;
    }
    if (bucketOp && bucketOp !== ev.op_id) flush();
    bucketOp = ev.op_id;
    bucket.push(ev);
  }
  flush();
  return out;
}

function ActivityRow({ event }: { event: ActivityEvent }) {
  const meta = ICONS[event.event] ?? { icon: MessageSquare, tone: "text-muted-foreground" };
  const Icon = meta.icon;
  const summary = summariseEvent(event);
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="flex items-start gap-2 text-xs"
      data-testid="activity-row"
      data-event={event.event}
    >
      <Icon className={cn("w-3.5 h-3.5 mt-0.5 shrink-0", meta.tone)} />
      <div className="flex-1 min-w-0">
        <div className="font-medium text-foreground/90 truncate">{event.event}</div>
        {summary && (
          <div className="text-muted-foreground truncate">{summary}</div>
        )}
      </div>
    </motion.div>
  );
}

function GroupCard({ opId, events }: { opId: string; events: ActivityEvent[] }) {
  const [open, setOpen] = useState(true);
  const last = events[events.length - 1];
  const meta = ICONS[last.event] ?? { icon: MessageSquare, tone: "text-muted-foreground" };
  const Icon = meta.icon;
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="rounded-md border border-border/60 bg-card/40"
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-muted/40 transition-colors"
      >
        <Icon className={cn("w-3.5 h-3.5 shrink-0", meta.tone)} />
        <span className="flex-1 text-left truncate">
          op <code className="text-[10px] text-muted-foreground">{opId.slice(0, 8)}</code>
          <span className="ml-2 text-muted-foreground">{events.length} events</span>
        </span>
        <span className="text-muted-foreground text-[10px]">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="px-2 pb-2 pt-0 space-y-1 border-t border-border/60">
          {events.map((e) => (
            <ActivityRow key={e.id} event={e} />
          ))}
        </div>
      )}
    </motion.div>
  );
}

function summariseEvent(ev: ActivityEvent): string {
  const d = ev.data || {};
  if (ev.event === "agent.tool_call") return `${d.tool ?? "tool"}: ${truncate(JSON.stringify(d.input ?? {}), 80)}`;
  if (ev.event === "agent.tool_result")
    return d.is_error ? `error: ${truncate(d.output_preview ?? "", 80)}` : truncate(d.output_preview ?? "", 80);
  if (ev.event === "agent.message") return truncate(d.text ?? "", 100);
  if (ev.event === "agent.done") return d.summary ? truncate(String(d.summary), 100) : "done";
  if (ev.event === "agent.error") return truncate(String(d.message ?? d.error_type ?? ""), 100);
  if (ev.event === "file.changed") return `${d.scope ?? ""} ${d.kind ?? ""} ${d.path ?? ""}`.trim();
  if (ev.event === "commit.created") return d.subject ? `${String(d.sha ?? "").slice(0, 7)} ${d.subject}` : "commit";
  if (ev.event === "lint.finding") return `${d.kind ?? "finding"}: ${truncate(d.message ?? "", 80)}`;
  return "";
}

function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}
