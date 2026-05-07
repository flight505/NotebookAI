"use client";

import { Link2, FileText } from "lucide-react";
import { motion } from "framer-motion";
import type { Article } from "@/lib/api";
import { cn } from "@/lib/cn";

interface BacklinksProps {
  current: Article | null;
  articles: Article[];
  onNavigate: (path: string) => void;
}

export function Backlinks({ current, articles, onNavigate }: BacklinksProps) {
  if (!current) return null;

  const linkers = articles.filter(
    (a) =>
      a.path !== current.path &&
      (a.outlinks?.includes(current.path) ||
        a.outlinks?.includes(current.path.replace(/\.md$/, "")) ||
        current.backlinks?.includes(a.path))
  );

  if (linkers.length === 0) {
    return (
      <div className="px-4 py-6 text-center">
        <Link2 className="w-5 h-5 mx-auto mb-2 text-muted-foreground/50" />
        <p className="text-xs text-muted-foreground">
          No backlinks yet. As other articles link here, they will appear in
          this list.
        </p>
      </div>
    );
  }

  return (
    <ul className="px-2 py-2 space-y-1" data-testid="backlinks-list">
      {linkers.map((a, i) => {
        const snippet = extractSnippet(a.content, current.path);
        return (
          <motion.li
            key={a.path}
            initial={{ opacity: 0, y: 2 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15, delay: i * 0.02 }}
          >
            <button
              onClick={() => onNavigate(a.path)}
              data-testid="backlinks-item"
              data-path={a.path}
              className={cn(
                "w-full text-left rounded-md p-2.5 transition-colors",
                "hover:bg-muted group"
              )}
            >
              <div className="flex items-center gap-2 mb-1">
                <FileText className="w-3.5 h-3.5 text-muted-foreground/70 shrink-0" />
                <span className="text-xs font-medium text-foreground truncate">
                  {a.title || a.path.replace(/\.md$/, "")}
                </span>
              </div>
              {snippet && (
                <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2 pl-5">
                  {snippet}
                </p>
              )}
            </button>
          </motion.li>
        );
      })}
    </ul>
  );
}

function extractSnippet(content: string, targetPath: string): string | null {
  const targetBase = targetPath.split("/").pop()?.replace(/\.md$/, "") ?? "";
  const re = new RegExp(`\\[\\[([^\\]]*${escapeRe(targetBase)}[^\\]]*)\\]\\]`, "i");
  const m = content.match(re);
  if (!m || m.index === undefined) return null;
  const radius = 80;
  const start = Math.max(0, m.index - radius);
  const end = Math.min(content.length, m.index + m[0].length + radius);
  let snippet = content.slice(start, end).replace(/\s+/g, " ").trim();
  if (start > 0) snippet = "… " + snippet;
  if (end < content.length) snippet = snippet + " …";
  return snippet;
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
