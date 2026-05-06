"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Folder, FileText, BookOpen } from "lucide-react";
import { motion } from "framer-motion";
import type { Article } from "@/lib/api";
import { cn } from "@/lib/cn";

interface TreeNode {
  name: string;
  path: string;
  children: Map<string, TreeNode>;
  article?: Article;
}

function buildTree(articles: Article[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map() };
  for (const a of articles) {
    const parts = a.path.split("/");
    let cursor = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLeaf = i === parts.length - 1;
      let next = cursor.children.get(part);
      if (!next) {
        next = {
          name: part,
          path: parts.slice(0, i + 1).join("/"),
          children: new Map(),
        };
        cursor.children.set(part, next);
      }
      if (isLeaf) next.article = a;
      cursor = next;
    }
  }
  return root;
}

function countArticles(node: TreeNode): number {
  let n = node.article ? 1 : 0;
  for (const c of node.children.values()) n += countArticles(c);
  return n;
}

interface ArticleTreeProps {
  articles: Article[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  loading?: boolean;
}

export function ArticleTree({
  articles,
  selectedPath,
  onSelect,
  loading,
}: ArticleTreeProps) {
  const root = useMemo(() => buildTree(articles), [articles]);

  if (loading) {
    return (
      <div className="p-3 space-y-1">
        {[...Array(6)].map((_, i) => (
          <div
            key={i}
            className="h-7 rounded-md bg-muted/40 animate-pulse"
            style={{ width: `${50 + ((i * 17) % 50)}%` }}
          />
        ))}
      </div>
    );
  }

  if (!articles.length) {
    return (
      <div className="p-6 text-center">
        <BookOpen className="w-7 h-7 mx-auto mb-3 text-muted-foreground/60" />
        <p className="text-sm font-medium text-foreground mb-1">
          No articles yet
        </p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          Try ingesting a source to get started — the agent will compile it into
          a wiki article.
        </p>
      </div>
    );
  }

  return (
    <ul role="tree" className="py-2 px-1 text-sm">
      {[...root.children.values()]
        .sort((a, b) => sortNodes(a, b))
        .map((child) => (
          <TreeRow
            key={child.path}
            node={child}
            depth={0}
            selectedPath={selectedPath}
            onSelect={onSelect}
          />
        ))}
    </ul>
  );
}

function sortNodes(a: TreeNode, b: TreeNode) {
  const aFolder = a.children.size > 0 && !a.article;
  const bFolder = b.children.size > 0 && !b.article;
  if (aFolder && !bFolder) return -1;
  if (!aFolder && bFolder) return 1;
  return a.name.localeCompare(b.name);
}

function TreeRow({
  node,
  depth,
  selectedPath,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  const isFolder = node.children.size > 0 && !node.article;
  const [open, setOpen] = useState(depth < 1);
  const selected = selectedPath === node.path;

  if (isFolder) {
    const total = countArticles(node);
    return (
      <li role="treeitem" aria-expanded={open}>
        <button
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "w-full flex items-center gap-1.5 py-1 pr-2 rounded-md hover:bg-muted transition-colors group",
            "text-left"
          )}
          style={{ paddingLeft: `${depth * 14 + 6}px` }}
        >
          <motion.span
            animate={{ rotate: open ? 90 : 0 }}
            transition={{ duration: 0.15 }}
            className="text-muted-foreground"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </motion.span>
          <Folder className="w-4 h-4 text-muted-foreground" />
          <span className="font-medium text-foreground truncate flex-1">
            {node.name}
          </span>
          <span className="text-[10px] tabular-nums text-muted-foreground/70 group-hover:text-muted-foreground">
            {total}
          </span>
        </button>
        {open && (
          <ul role="group">
            {[...node.children.values()]
              .sort((a, b) => sortNodes(a, b))
              .map((c) => (
                <TreeRow
                  key={c.path}
                  node={c}
                  depth={depth + 1}
                  selectedPath={selectedPath}
                  onSelect={onSelect}
                />
              ))}
          </ul>
        )}
      </li>
    );
  }

  const title = node.article?.title ?? node.name.replace(/\.md$/, "");
  return (
    <li role="treeitem" aria-selected={selected}>
      <button
        onClick={() => onSelect(node.path)}
        className={cn(
          "w-full flex items-center gap-1.5 py-1 pr-2 rounded-md text-left transition-colors",
          selected
            ? "bg-accent/10 text-foreground"
            : "hover:bg-muted text-muted-foreground hover:text-foreground"
        )}
        style={{ paddingLeft: `${depth * 14 + 6}px` }}
      >
        <span className="w-3.5" />
        <FileText
          className={cn(
            "w-4 h-4 shrink-0",
            selected ? "text-accent" : "text-muted-foreground/70"
          )}
        />
        <span
          className={cn(
            "truncate flex-1",
            selected && "font-medium text-foreground"
          )}
        >
          {title}
        </span>
      </button>
    </li>
  );
}
