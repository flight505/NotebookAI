"use client";

import Link from "next/link";
import { BookOpen } from "lucide-react";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/cn";

export interface CitationChipProps {
  articlePath: string; // "wiki/foo/bar.md" or "foo/bar.md"
  quote?: string;
  score?: number | null;
  anchor?: string;
  className?: string;
}

function basenameOf(path: string): string {
  const parts = path.split("/").filter(Boolean);
  const last = parts[parts.length - 1] ?? path;
  return last.replace(/\.md$/i, "");
}

function readPath(path: string): string {
  // Read mode expects paths relative to wiki/.
  return path.startsWith("wiki/") ? path.slice("wiki/".length) : path;
}

export function CitationChip({
  articlePath,
  quote,
  score,
  anchor,
  className,
}: CitationChipProps) {
  const label = basenameOf(articlePath);
  const href = `/read?article=${encodeURIComponent(readPath(articlePath))}${
    anchor ? `#${anchor}` : ""
  }`;

  const tooltipContent = (
    <span className="flex flex-col gap-1 max-w-xs whitespace-normal text-left">
      <span className="font-semibold">{articlePath}</span>
      {quote && (
        <span className="italic text-[0.95em] opacity-90 line-clamp-3">
          “{quote}”
        </span>
      )}
      {typeof score === "number" && (
        <span className="opacity-70 text-[0.8em]">
          score: {score.toFixed(2)}
        </span>
      )}
    </span>
  );

  return (
    <Tooltip content={tooltipContent} side="top">
      <Link
        href={href as any}
        data-testid="citation-chip"
        data-article-path={articlePath}
        className={cn(
          "inline-flex items-center gap-1 px-1.5 py-0.5",
          "rounded-md text-xs font-medium",
          "bg-subtle hover:bg-muted text-muted-foreground hover:text-foreground",
          "border border-border transition-colors",
          className,
        )}
      >
        <BookOpen className="w-3 h-3" />
        <span className="max-w-[12rem] truncate">{label}</span>
      </Link>
    </Tooltip>
  );
}
